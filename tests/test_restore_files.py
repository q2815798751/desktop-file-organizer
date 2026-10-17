"""
restore_files.py 的单元测试（标准库 unittest，零新依赖）。

数据安全红线：本脚本会**真实移动文件**。所有用例都在
`tempfile.TemporaryDirectory()` 里造目录，并 `mock.patch("config.CONFIG_PATH", 临时路径)`
打桩配置路径。

⚠️ **安全承诺必须可验证，不能只是「看起来」**（AW-21）：
旧代码把配置路径做成**本模块的模块级常量**、把桌面路径在 **import 时**绑定，
于是 `mock.patch` 打在「模块级常量」/「import 时绑定」这两个目标上会**静默失效**——
测试看着安全，把修复撤掉后却会真的把文件搬到 `C:\\Users\\<user>\\Desktop`。
所以 `RestoreTestBase.setUp` 除了打桩，还**显式断言** `restore_files.resolve_desktop({})`
落在 `self.tmp` 内：一旦重定向没生效（或回退桌面被改回 import 时绑定），
测试会在 setUp 阶段**直接报错**，绝不会真的去动真实桌面。
不导入任何 GUI 模块，不运行 `main.py`。

运行：python -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import config  # noqa: E402
import file_manager  # noqa: E402
import restore_files  # noqa: E402


# AW-14：`os.path.abspath("con")` 是否会把 Windows 保留设备名解析成设备路径 `\\.\con`。
# 这是 **Windows 版本相关** 的行为：Windows 10 会（于是 commonpath 抛 ValueError），
# 而 GitHub Actions 的 windows-latest（Windows Server 2025）不会——同样 Python 3.14，
# 本机跑绿、CI 上 `_category_dir` 返回 `...\storage\con` 而不是 None。
# 该行为只影响 `TestCategoryDir.test_reserved_device_name_hits_valueerror_branch`
# （它专门覆盖 `_category_dir` 的 `except ValueError` 分支），故用这个探测与环境对齐：
# 环境不提供该分支时**跳过**，而不是把用例改成对任何环境都恒真（那等于没测）。
_ABSPATH_MAPS_DEVICE_NAMES = os.path.abspath("con").startswith("\\\\.\\")


class RestoreTestBase(unittest.TestCase):
    """
    把 CONFIG_PATH 打桩到临时目录，绝不动仓库根目录的 config.json。

    见模块 docstring：这里的打桩**不是**安全承诺本身，`_assert_fallback_desktop_inside_tmp`
    才是——它把「打桩确实生效」变成一条**会失败的断言**。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.config_path = os.path.join(self.tmp, "config.json")

        # (1) 把 HOME / USERPROFILE 重定向到临时目录（双保险：覆盖直接读环境变量的代码）
        env_patch = mock.patch.dict(
            os.environ, {"HOME": self.tmp, "USERPROFILE": self.tmp}
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)

        # (2) 把 ~ 重定向到临时目录：resolve_desktop / resolve_storage_root 的**回退**
        #     只会落到 self.tmp 里
        exp_patch = mock.patch(
            "os.path.expanduser",
            side_effect=lambda p: p.replace("~", self.tmp),
        )
        exp_patch.start()
        self.addCleanup(exp_patch.stop)

        # (3) 把配置路径打桩到临时文件（只对「调用时读 config.CONFIG_PATH」的写法有效）
        cfg_patch = mock.patch("config.CONFIG_PATH", self.config_path)
        cfg_patch.start()
        self.addCleanup(cfg_patch.stop)

        # 🔴 护栏：断言重定向**真的生效**。失效即报错，绝不带着「假安全」往下跑。
        self._assert_fallback_desktop_inside_tmp()

    def _assert_fallback_desktop_inside_tmp(self):
        """断言 `resolve_desktop` 的**回退值**落在 `self.tmp` 内（重定向生效的证明）。"""
        got = os.path.abspath(restore_files.resolve_desktop({}))
        tmp_abs = os.path.abspath(self.tmp)
        self.assertTrue(
            got == tmp_abs or got.startswith(tmp_abs + os.sep),
            f"回退桌面 {got!r} 不在临时目录 {tmp_abs!r} 内——"
            "打桩已失效，继续跑会碰到真实桌面，立即中止。",
        )

    def write_config(self, cfg):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)


def _make_junction(link, target):
    """
    在 Windows 上创建 junction（`mklink /J`，免管理员）。成功返回 True。

    测试里**只在 `tempfile.TemporaryDirectory()` 内**建链接，并用
    `os.rmdir(link)`（只删链接本身、不动目标）清理。
    """
    try:
        rc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link, target],
            capture_output=True,
        ).returncode
    except OSError:
        return False
    return rc == 0 and os.path.isdir(link)


# ── category_folders：遍历配置里的实际分类（含自建分类） ─────────

class TestCategoryFolders(RestoreTestBase):

    def test_includes_user_created_category(self):
        # 旧脚本硬编码 5 个默认名 → 自建分类「项目资料」永远扫不到
        cfg = {
            "categories": [
                {"name": "办公文件", "extensions": ["doc"], "folder": "办公文件"},
                {"name": "项目资料", "extensions": ["md"], "folder": "项目资料"},
            ]
        }
        folders = dict(restore_files.category_folders(cfg))
        self.assertIn("项目资料", folders)
        self.assertEqual(folders["项目资料"], "项目资料")

    def test_uses_folder_field_when_different_from_name(self):
        # folder 与显示名不一致时，磁盘目录名必须取 folder（否则扫错目录）
        cfg = {"categories": [{"name": "发票", "extensions": [], "folder": "发票单据"}]}
        self.assertEqual(restore_files.category_folders(cfg), [("发票", "发票单据")])

    def test_falls_back_to_name_when_folder_missing(self):
        cfg = {"categories": [{"name": "图片", "extensions": ["png"]}]}
        self.assertEqual(restore_files.category_folders(cfg), [("图片", "图片")])

    def test_falls_back_to_name_when_folder_empty(self):
        cfg = {"categories": [{"name": "图片", "extensions": [], "folder": ""}]}
        self.assertEqual(restore_files.category_folders(cfg), [("图片", "图片")])

    def test_dedupes_shared_folder_keeping_order(self):
        cfg = {
            "categories": [
                {"name": "A", "extensions": [], "folder": "共用"},
                {"name": "B", "extensions": [], "folder": "共用"},
                {"name": "C", "extensions": [], "folder": "C"},
            ]
        }
        self.assertEqual(
            restore_files.category_folders(cfg),
            [("A", "共用"), ("C", "C")],
        )

    def test_dedupes_equivalent_spellings_by_abspath(self):
        # AW-21：`shared` 与 `.\shared` 是同一个目录，旧实现按原始字符串去重 → 会重复。
        cfg = {
            "categories": [
                {"name": "A", "extensions": [], "folder": "shared"},
                {"name": "B", "extensions": [], "folder": os.path.join(".", "shared")},
            ]
        }
        self.assertEqual(restore_files.category_folders(cfg), [("A", "shared")])

    def test_skips_bad_entries(self):
        cfg = {
            "categories": [
                "not-a-dict",                    # 非字典
                {"extensions": []},              # 既无 name 也无 folder
                {"name": "   ", "folder": "  "},  # 名字全空白
                {"name": "坏folder", "folder": 123},  # folder 非字符串 → 跳过（与 file_manager 一致）
                {"name": "正常", "folder": "正常"},
            ]
        }
        self.assertEqual(restore_files.category_folders(cfg), [("正常", "正常")])

    def test_empty_config_yields_nothing(self):
        self.assertEqual(restore_files.category_folders({}), [])
        self.assertEqual(restore_files.category_folders(None), [])


# ── resolve_desktop / resolve_storage_root 的取值与回退 ────────

class TestResolvePaths(RestoreTestBase):

    def test_desktop_uses_config_value(self):
        cfg = {"desktop_path": os.path.join(self.tmp, "OneDrive", "Desktop")}
        self.assertEqual(
            restore_files.resolve_desktop(cfg),
            os.path.join(self.tmp, "OneDrive", "Desktop"),
        )

    def test_desktop_falls_back_to_home_when_empty(self):
        with mock.patch("os.path.expanduser", side_effect=lambda p: p.replace("~", self.tmp)):
            got = restore_files.resolve_desktop({"desktop_path": ""})
        self.assertEqual(got, os.path.join(self.tmp, "Desktop"))

    def test_storage_uses_config_value(self):
        cfg = {"storage_path": os.path.join(self.tmp, "store")}
        self.assertEqual(restore_files.resolve_storage_root(cfg), os.path.join(self.tmp, "store"))

    def test_storage_falls_back_when_empty(self):
        with mock.patch("os.path.expanduser", side_effect=lambda p: p.replace("~", self.tmp)):
            got = restore_files.resolve_storage_root({})
        self.assertEqual(
            got, os.path.join(self.tmp, "Documents", restore_files._DEFAULT_STORAGE_NAME)
        )


# ── _category_dir：词法校验 + realpath 复检（含 ValueError 分支） ──

class TestCategoryDir(RestoreTestBase):

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "storage")
        os.makedirs(self.root)

    def test_normal_folder_resolves_inside_root(self):
        self.assertEqual(
            restore_files._category_dir(self.root, "pics"),
            os.path.join(self.root, "pics"),
        )

    def test_absolute_folder_is_skipped_and_logged(self):
        with self.assertLogs("restore_files", level="WARNING"):
            self.assertIsNone(restore_files._category_dir(self.root, self.tmp))

    def test_parent_escape_is_skipped_and_logged(self):
        with self.assertLogs("restore_files", level="WARNING"):
            self.assertIsNone(
                restore_files._category_dir(self.root, os.path.join("..", "evil"))
            )

    @unittest.skipUnless(
        _ABSPATH_MAPS_DEVICE_NAMES,
        "本平台不把保留设备名解析成设备路径（Windows 10 会、Windows Server 2025 不会）："
        "`_category_dir` 因此不会走 `except ValueError` 分支，本用例覆盖的分支在此环境不存在",
    )
    def test_reserved_device_name_hits_valueerror_branch(self):
        # `con` 经 os.path.abspath 变成 `\\.\con`（设备路径）→ commonpath 抛 ValueError。
        # 这正是 _category_dir 里 `except ValueError` 分支的真实触发路径（旧测试零覆盖）。
        for folder in ("con", "aux", "nul"):
            with self.assertLogs("restore_files", level="WARNING"):
                self.assertIsNone(
                    restore_files._category_dir(self.root, folder),
                    f"保留设备名 {folder!r} 必须被跳过",
                )

    def test_drive_relative_path_hits_valueerror_branch(self):
        # `D:evil` 带盘符但非绝对路径 → join 丢掉 root → commonpath 抛 ValueError（不同盘符）。
        with self.assertLogs("restore_files", level="WARNING"):
            self.assertIsNone(restore_files._category_dir(self.root, "D:evil"))

    @unittest.skipUnless(os.name == "nt", "junction 只在 Windows 上可测")
    def test_real_junction_escape_is_skipped(self):
        """真实 mklink /J：词法校验放行、realpath 复检必须拒绝（这是 AW-21 的核心洞）。"""
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        link = os.path.join(self.root, "evil")
        if not _make_junction(link, outside):
            self.skipTest("本环境无法创建 junction（mklink 失败）")
        self.addCleanup(lambda: os.rmdir(link) if os.path.isdir(link) else None)

        # 词法校验确实放行——这正是逃逸能发生的原因（证明 realpath 复检是必需的）
        self.assertIsNone(file_manager.category_folder_error(self.root, "evil"))
        with self.assertLogs("restore_files", level="WARNING"):
            self.assertIsNone(
                restore_files._category_dir(self.root, "evil"),
                "指向根外的 junction 必须被 realpath 复检拒绝",
            )


# ── build_restore_plan：纯函数，只读文件系统 ────────────────────

class TestBuildRestorePlan(RestoreTestBase):

    def setUp(self):
        super().setUp()
        self.desktop = os.path.join(self.tmp, "ConfiguredDesktop")
        self.storage = os.path.join(self.tmp, "storage")
        os.makedirs(self.desktop)
        os.makedirs(self.storage)

    def _make_category(self, folder, *filenames):
        d = os.path.join(self.storage, folder)
        os.makedirs(d, exist_ok=True)
        for fn in filenames:
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                f.write(fn)
        return d

    def test_desktop_comes_from_config_not_hardcoded_home(self):
        cfg = {"desktop_path": self.desktop, "storage_path": self.storage, "categories": []}
        desktop, _ = restore_files.build_restore_plan(cfg)
        self.assertEqual(desktop, self.desktop)
        # 关键判别点：绝不是写死的 ~/Desktop
        self.assertNotEqual(desktop, os.path.join(os.path.expanduser("~"), "Desktop"))

    def test_plan_covers_user_created_category(self):
        self._make_category("项目资料", "需求.md", "设计.md")
        cfg = {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": [
                {"name": "办公文件", "extensions": ["doc"], "folder": "办公文件"},
                {"name": "项目资料", "extensions": ["md"], "folder": "项目资料"},
            ],
        }
        desktop, entries = restore_files.build_restore_plan(cfg)
        labels = {e[0] for e in entries}
        names = {e[3] for e in entries}
        self.assertIn("项目资料", labels, "自建分类必须出现在恢复清单里")
        self.assertEqual(names, {"需求.md", "设计.md"})

    def test_plan_uses_folder_field_for_directory(self):
        # 显示名「发票」但磁盘目录是「发票单据」→ 必须按 folder 扫描
        self._make_category("发票单据", "a.pdf")
        cfg = {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": [{"name": "发票", "extensions": ["pdf"], "folder": "发票单据"}],
        }
        _, entries = restore_files.build_restore_plan(cfg)
        self.assertEqual([(e[0], e[3]) for e in entries], [("发票", "a.pdf")])

    def test_plan_dest_dir_is_config_desktop(self):
        self._make_category("图片", "a.png")
        cfg = {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": [{"name": "图片", "extensions": ["png"], "folder": "图片"}],
        }
        _, entries = restore_files.build_restore_plan(cfg)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][2], self.desktop)

    def test_plan_skips_missing_category_dir(self):
        self._make_category("图片", "a.png")
        cfg = {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": [
                {"name": "图片", "extensions": [], "folder": "图片"},
                {"name": "不存在的分类", "extensions": [], "folder": "不存在的分类"},
            ],
        }
        _, entries = restore_files.build_restore_plan(cfg)
        self.assertEqual({e[0] for e in entries}, {"图片"})

    def test_plan_only_includes_files_not_subdirs(self):
        d = self._make_category("图片", "a.png")
        os.makedirs(os.path.join(d, "子目录"))
        cfg = {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": [{"name": "图片", "extensions": [], "folder": "图片"}],
        }
        _, entries = restore_files.build_restore_plan(cfg)
        self.assertEqual([e[3] for e in entries], ["a.png"])

    def test_plan_rejects_folder_escaping_storage_root(self):
        # folder 越界（..\..\outside）→ 不得扫描存储根之外
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as f:
            f.write("secret")
        cfg = {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": [{"name": "逃逸", "extensions": [], "folder": os.path.join("..", "outside")}],
        }
        _, entries = restore_files.build_restore_plan(cfg)
        self.assertEqual(entries, [], "越界 folder 必须被跳过，不能扫描存储根之外")

    def test_plan_rejects_absolute_folder(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside, exist_ok=True)
        with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as f:
            f.write("secret")
        cfg = {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": [{"name": "逃逸", "extensions": [], "folder": outside}],
        }
        _, entries = restore_files.build_restore_plan(cfg)
        self.assertEqual(entries, [])

    @unittest.skipUnless(os.name == "nt", "junction 只在 Windows 上可测")
    def test_plan_skips_junction_category_pointing_outside(self):
        # 存储根里造 junction 指向根外：词法校验放行 → 旧实现会列出根外文件。
        # AW-21 的 realpath 复检必须跳过该分类，根外文件一个都不能进计划。
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "SECRET.txt"), "w", encoding="utf-8") as f:
            f.write("secret")
        link = os.path.join(self.storage, "evil")
        if not _make_junction(link, outside):
            self.skipTest("本环境无法创建 junction（mklink 失败）")
        self.addCleanup(lambda: os.rmdir(link) if os.path.isdir(link) else None)

        # 词法校验会放行（这正是逃逸能发生的原因）
        self.assertIsNone(file_manager.category_folder_error(self.storage, "evil"))

        cfg = {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": [{"name": "逃逸", "extensions": [], "folder": "evil"}],
        }
        with self.assertLogs("restore_files", level="WARNING"):
            _, entries = restore_files.build_restore_plan(cfg)
        self.assertEqual(entries, [], "指向根外的 junction 分类必须被跳过")
        self.assertNotIn("SECRET.txt", {e[3] for e in entries})


# ── 端到端：restore() 真的按配置把文件搬回配置里的桌面 ─────────

class TestRestoreEndToEnd(RestoreTestBase):

    def setUp(self):
        super().setUp()
        self.desktop = os.path.join(self.tmp, "ConfiguredDesktop")
        self.storage = os.path.join(self.tmp, "storage")
        # 假家目录：把 ~ 重定向到这里，确保即使修复被撤掉也不会写到真实桌面
        self.fake_home = os.path.join(self.tmp, "fakehome")
        os.makedirs(self.desktop)
        os.makedirs(self.storage)
        os.makedirs(self.fake_home)

        exp = mock.patch(
            "os.path.expanduser",
            side_effect=lambda p: p.replace("~", self.fake_home),
        )
        exp.start()
        self.addCleanup(exp.stop)

    def _seed(self, folder, filename):
        d = os.path.join(self.storage, folder)
        os.makedirs(d, exist_ok=True)
        src = os.path.join(d, filename)
        with open(src, "w", encoding="utf-8") as f:
            f.write("payload")
        return src

    def test_restore_moves_custom_category_file_to_config_desktop(self):
        src = self._seed("项目资料", "需求.md")
        self.write_config(
            {
                "categories": [
                    {"name": "办公文件", "extensions": ["doc"], "folder": "办公文件"},
                    {"name": "项目资料", "extensions": ["md"], "folder": "项目资料"},
                ],
                "desktop_path": self.desktop,
                "storage_path": self.storage,
                "initialized": True,
            }
        )

        with contextlib.redirect_stdout(io.StringIO()) as out:
            restore_files.restore()

        restored = os.path.join(self.desktop, "需求.md")
        self.assertTrue(os.path.isfile(restored), "自建分类的文件必须被恢复到配置桌面")
        self.assertFalse(os.path.exists(src), "源文件应已移走")
        self.assertIn("共恢复 1 个文件", out.getvalue())

        # 关键：绝不能落在写死的 ~/Desktop（= fake_home/Desktop）
        self.assertFalse(os.path.exists(os.path.join(self.fake_home, "Desktop")))
        # 全程只在临时目录内
        self.assertTrue(os.path.abspath(restored).startswith(self.tmp))

    def test_restore_conflict_renames_without_clobbering(self):
        src = self._seed("图片", "a.png")
        existing = os.path.join(self.desktop, "a.png")
        with open(existing, "w", encoding="utf-8") as f:
            f.write("KEEP")
        self.write_config(
            {
                "categories": [{"name": "图片", "extensions": ["png"], "folder": "图片"}],
                "desktop_path": self.desktop,
                "storage_path": self.storage,
                "initialized": True,
            }
        )

        with contextlib.redirect_stdout(io.StringIO()):
            restore_files.restore()

        # 桌面原有文件必须原样保留，新文件改名恢复
        with open(existing, encoding="utf-8") as f:
            self.assertEqual(f.read(), "KEEP")
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "a_restored(1).png")))
        self.assertFalse(os.path.exists(src))

    def test_restore_reads_config_via_load_config(self):
        # 证明 restore() 走的是 config.load_config()（CONFIG_PATH 已被打桩到临时路径）
        self._seed("图片", "b.png")
        self.write_config(
            {
                "categories": [{"name": "图片", "extensions": ["png"], "folder": "图片"}],
                "desktop_path": self.desktop,
                "storage_path": self.storage,
                "initialized": True,
            }
        )
        with contextlib.redirect_stdout(io.StringIO()):
            restore_files.restore()
        self.assertTrue(os.path.isfile(os.path.join(self.desktop, "b.png")))

    def test_restore_reports_move_failure_and_keeps_source(self):
        # AW-21 补覆盖：restore() 里 `except OSError`（旧测试零覆盖）。
        # 用 spy 掉包 shutil.move 抛 OSError，断言失败被打印、不计入成功数、源文件保留。
        src = self._seed("图片", "a.png")
        self.write_config(
            {
                "categories": [{"name": "图片", "extensions": ["png"], "folder": "图片"}],
                "desktop_path": self.desktop,
                "storage_path": self.storage,
                "initialized": True,
            }
        )

        with mock.patch("restore_files.shutil.move", side_effect=OSError("boom")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                restore_files.restore()

        text = out.getvalue()
        self.assertIn("失败: a.png - boom", text)
        self.assertIn("共恢复 0 个文件", text)
        self.assertTrue(os.path.isfile(src), "移动失败时源文件必须保留在存储目录")


# ── _resolve_dest：第二次改名冲突（AW-21 补覆盖） ────────────────

class TestResolveDest(RestoreTestBase):

    def setUp(self):
        super().setUp()
        self.desktop = os.path.join(self.tmp, "d")
        os.makedirs(self.desktop)

    def _touch(self, name):
        with open(os.path.join(self.desktop, name), "w", encoding="utf-8") as f:
            f.write("x")

    def test_no_conflict_keeps_name(self):
        self.assertEqual(
            restore_files._resolve_dest(self.desktop, "a.png"),
            os.path.join(self.desktop, "a.png"),
        )

    def test_first_conflict_uses_counter_one(self):
        self._touch("a.png")
        self.assertEqual(
            restore_files._resolve_dest(self.desktop, "a.png"),
            os.path.join(self.desktop, "a_restored(1).png"),
        )

    def test_second_conflict_increments_counter(self):
        # AW-21 补覆盖：`a_restored(1)` 也被占用时，循环必须继续到 `a_restored(2)`。
        self._touch("a.png")
        self._touch("a_restored(1).png")
        self.assertEqual(
            restore_files._resolve_dest(self.desktop, "a.png"),
            os.path.join(self.desktop, "a_restored(2).png"),
        )

    def test_third_conflict_increments_counter(self):
        self._touch("a.png")
        self._touch("a_restored(1).png")
        self._touch("a_restored(2).png")
        self.assertEqual(
            restore_files._resolve_dest(self.desktop, "a.png"),
            os.path.join(self.desktop, "a_restored(3).png"),
        )


# ── 端到端：junction 逃逸下的 restore()（根外文件一个都不能被搬） ──

class TestRestoreJunctionEscape(RestoreTestBase):

    def setUp(self):
        super().setUp()
        self.desktop = os.path.join(self.tmp, "ConfiguredDesktop")
        self.storage = os.path.join(self.tmp, "storage")
        os.makedirs(self.desktop)
        os.makedirs(self.storage)

    @unittest.skipUnless(os.name == "nt", "junction 只在 Windows 上可测")
    def test_restore_does_not_move_files_from_outside_junction(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        secret = os.path.join(outside, "SECRET.txt")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("secret-payload")

        link = os.path.join(self.storage, "evil")
        if not _make_junction(link, outside):
            self.skipTest("本环境无法创建 junction（mklink 失败）")
        self.addCleanup(lambda: os.rmdir(link) if os.path.isdir(link) else None)

        # 对照组：一个正常分类
        d = os.path.join(self.storage, "图片")
        os.makedirs(d)
        with open(os.path.join(d, "a.png"), "w", encoding="utf-8") as f:
            f.write("png")

        self.write_config(
            {
                "categories": [
                    {"name": "图片", "extensions": ["png"], "folder": "图片"},
                    {"name": "逃逸", "extensions": [], "folder": "evil"},
                ],
                "desktop_path": self.desktop,
                "storage_path": self.storage,
                "initialized": True,
            }
        )

        # spy 掉包 shutil.move：**记录**搬移调用、不真的搬（红线：测试里别真搬）。
        # 记录型 spy 是判别性的——若复检失效，根外文件会被记录成搬移源，断言即变红。
        calls = []

        def spy_move(src, dst):
            calls.append((os.path.abspath(src), os.path.abspath(dst)))

        with mock.patch("restore_files.shutil.move", side_effect=spy_move):
            with contextlib.redirect_stdout(io.StringIO()):
                restore_files.restore()

        outside_abs = os.path.abspath(outside)
        moved_srcs = [s for s, _ in calls]
        self.assertFalse(
            any(
                s == outside_abs or s.startswith(outside_abs + os.sep)
                for s in moved_srcs
            ),
            f"根外文件绝不能被搬走，实际搬移调用：{calls}",
        )
        # 对照组：正常分类的文件确实进了搬移调用
        self.assertEqual([os.path.basename(s) for s in moved_srcs], ["a.png"])
        # 根外文件原样还在、内容没变
        self.assertTrue(os.path.isfile(secret))
        with open(secret, encoding="utf-8") as f:
            self.assertEqual(f.read(), "secret-payload")


# ── 护栏本身：setUp 的「回退桌面落在临时目录内」断言必须有判别力 ──

class TestSetupGuard(RestoreTestBase):

    def test_fallback_desktop_is_redirected_into_tmp(self):
        # 正向：当前环境下回退桌面确实落在临时目录内
        got = os.path.abspath(restore_files.resolve_desktop({}))
        self.assertTrue(got.startswith(os.path.abspath(self.tmp) + os.sep))

    def test_guard_detects_fallback_outside_tmp(self):
        # 判别性：若回退桌面落到别处（模拟打桩失效 / import 时绑定真实桌面），
        # `_assert_fallback_desktop_inside_tmp` 必须**报错**——这就是「撤掉修复也不碰真实桌面」
        # 这条承诺真正成立的原因：护栏会先炸，测试不会带着假安全继续跑。
        outside = os.path.join(os.path.abspath(os.sep), "RealDesktop")
        with mock.patch("restore_files.resolve_desktop", return_value=outside):
            with self.assertRaises(AssertionError):
                self._assert_fallback_desktop_inside_tmp()


# ── 读配置失败：记录 + 回退默认（AW-8） ─────────────────────
#
# 旧实现（AW-6 之前）在 `_storage_root()` 里 `except Exception: pass`：配置读不出来
# 就静默改用默认路径，用户和开发者都看不到。现在走 `_load_config_or_default()`：
# 失败记 WARNING，回退空配置（→ 默认路径 + 空分类清单 → 一个文件都不动，fail-closed）。

class TestUnreadableConfig(RestoreTestBase):

    def test_read_failure_logs_and_returns_empty_config(self):
        with mock.patch(
            "restore_files.config.load_config", side_effect=OSError("disk on fire")
        ):
            with self.assertLogs("restore_files", level="WARNING") as cm:
                cfg = restore_files._load_config_or_default()

        self.assertEqual(cfg, {}, "读失败应回退空配置")
        self.assertIn(
            "disk on fire", "\n".join(cm.output), "读配置失败必须被记录，不能静默"
        )

    def test_success_returns_config_unchanged(self):
        sentinel = {"categories": [{"name": "图片"}], "desktop_path": "D:/d"}
        with mock.patch(
            "restore_files.config.load_config", return_value=sentinel
        ):
            self.assertIs(restore_files._load_config_or_default(), sentinel)

    def test_restore_with_unreadable_config_moves_nothing(self):
        # 端到端：配置读不出来时，restore() 必须「记录 + 什么都不搬」（fail-closed）。
        # spy 掉包 shutil.move：只记录调用，绝不真搬。
        calls = []
        with mock.patch(
            "restore_files.config.load_config", side_effect=OSError("unreadable")
        ), mock.patch(
            "restore_files.shutil.move",
            side_effect=lambda *a, **k: calls.append(a),
        ):
            with self.assertLogs("restore_files", level="WARNING") as cm:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    restore_files.restore()

        self.assertEqual(calls, [], "读不到配置时不得搬动任何文件")
        self.assertIn("unreadable", "\n".join(cm.output), "失败必须被记录")
        self.assertIn("共恢复 0 个文件", out.getvalue())


if __name__ == "__main__":
    unittest.main()
