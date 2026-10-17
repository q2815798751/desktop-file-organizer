"""
init_folders（first_run 分支）/ _move_matching_files / get_files_in_category 的单元测试。
（标准库 unittest，零新依赖；不导入 GUI 模块。）

数据安全：
- 全部在 tempfile.TemporaryDirectory() 里造「假桌面」「假存储根」，绝不碰真实目录。
- ⚠️ config.json 地雷：init_folders 会调用 config.save_config，而 config.CONFIG_PATH
  在非打包状态下指向仓库根目录。因此 setUp 里**先把 config.CONFIG_PATH 打桩到临时目录**，
  跑完 git status 必须干净。

运行：python -m unittest discover -s tests -v
"""
import errno
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import config        # noqa: E402
import file_manager  # noqa: E402


# 精简分类表（仅测试用）
CATEGORIES = [
    {"name": "办公文件", "extensions": ["doc", "docx", "pdf"], "folder": "办公文件"},
    {"name": "压缩包", "extensions": ["zip", "rar"], "folder": "压缩包"},
    {"name": "其他", "extensions": [], "folder": "其他"},
]


class InitFoldersTestBase(unittest.TestCase):
    """假桌面 + 假存储根 + 打桩 config.CONFIG_PATH。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.desktop = os.path.join(self.tmp, "Desktop")
        self.storage = os.path.join(self.tmp, "storage")
        os.makedirs(self.desktop)
        os.makedirs(self.storage)
        self.config_path = os.path.join(self.tmp, "config.json")

        # config.json 地雷：init_folders → save_config 会写这个路径
        patcher = mock.patch("config.CONFIG_PATH", self.config_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_config(self, initialized=False, categories=None):
        return {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": (
                categories if categories is not None
                else [dict(c) for c in CATEGORIES]
            ),
            "initialized": initialized,
        }

    def write_file(self, path, content="x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def read_file(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def assertInsideTmp(self, path):
        self.assertTrue(
            os.path.abspath(path).startswith(os.path.abspath(self.tmp) + os.sep),
            f"路径 {path!r} 不在临时目录 {self.tmp!r} 内",
        )


# ── init_folders（首次运行分支：真正执行搬移的那条）────────

class TestInitFoldersFirstRun(InitFoldersTestBase):

    def test_first_run_moves_matching_desktop_files(self):
        cfg = self.make_config(initialized=False)
        src = self.write_file(os.path.join(self.desktop, "report.doc"), "hi")
        keep = self.write_file(os.path.join(self.desktop, "keep.txt"), "stay")

        result = file_manager.init_folders(cfg)

        dest = os.path.join(self.storage, "办公文件", "report.doc")
        self.assertTrue(os.path.isfile(dest), "首次运行应把匹配文件搬进分类文件夹")
        self.assertEqual(self.read_file(dest), "hi")
        self.assertFalse(os.path.exists(src), "搬移后桌面上不应再有源文件")
        self.assertTrue(os.path.exists(keep), "不匹配的文件必须留在桌面")
        self.assertInsideTmp(dest)
        # 新行为：返回结构化统计，成功 1、失败 0
        self.assertEqual(result.moved, 1)
        self.assertEqual(result.failed, 0)

    def test_first_run_sets_initialized_and_saves_config(self):
        cfg = self.make_config(initialized=False)
        self.write_file(os.path.join(self.desktop, "report.doc"), "hi")

        file_manager.init_folders(cfg)

        self.assertTrue(cfg["initialized"], "首次运行后内存配置应标记 initialized")
        self.assertTrue(os.path.exists(self.config_path), "首次运行后应落盘配置")
        import json
        with open(self.config_path, encoding="utf-8") as f:
            self.assertTrue(json.load(f)["initialized"])

    def test_first_run_creates_all_category_folders(self):
        cfg = self.make_config(initialized=False)
        file_manager.init_folders(cfg)
        for cat in CATEGORIES:
            self.assertTrue(
                os.path.isdir(os.path.join(self.storage, cat["folder"])),
                f"分类文件夹 {cat['folder']} 应被创建",
            )

    def test_initialized_true_still_creates_folders_but_moves_nothing(self):
        cfg = self.make_config(initialized=True)
        src = self.write_file(os.path.join(self.desktop, "report.doc"), "hi")

        file_manager.init_folders(cfg)

        self.assertTrue(os.path.exists(src), "已初始化时不得再搬移桌面文件")
        self.assertTrue(os.path.isdir(os.path.join(self.storage, "办公文件")))

    def test_first_run_only_moves_top_level_files(self):
        cfg = self.make_config(initialized=False)
        nested = self.write_file(os.path.join(self.desktop, "sub", "deep.doc"), "deep")

        file_manager.init_folders(cfg)

        self.assertTrue(os.path.exists(nested), "子文件夹里的文件不应被搬移")

    def test_first_run_name_conflict_renames_and_preserves_existing(self):
        cfg = self.make_config(initialized=False)
        existing = self.write_file(
            os.path.join(self.storage, "办公文件", "a.doc"), "old"
        )
        self.write_file(os.path.join(self.desktop, "a.doc"), "new")

        file_manager.init_folders(cfg)

        self.assertEqual(self.read_file(existing), "old", "同名旧文件不得被覆盖")
        moved = os.path.join(self.storage, "办公文件", "a(1).doc")
        self.assertTrue(os.path.isfile(moved))
        self.assertEqual(self.read_file(moved), "new")

    def test_first_run_move_failure_keeps_file_on_desktop(self):
        cfg = self.make_config(initialized=False)
        src = self.write_file(os.path.join(self.desktop, "report.doc"), "keep")

        with mock.patch("file_manager.shutil.move", side_effect=OSError("boom")):
            result = file_manager.init_folders(cfg)

        self.assertTrue(os.path.exists(src), "搬移失败时源文件必须留在桌面")
        self.assertFalse(
            os.path.exists(os.path.join(self.storage, "办公文件", "report.doc"))
        )
        # 新行为：失败不再被静默吞掉，而是被统计并带上原因
        self.assertEqual(result.moved, 0)
        self.assertEqual(result.failed, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], OSError)


# ── AW-19：坏配置不得让启动崩掉（init_folders 跳过非法分类）──

class TestUnsafeCategoryDoesNotCrashStartup(InitFoldersTestBase):
    """
    AW-3 引入的回归：非法 `folder` 会让 `init_folders` 原样抛 `UnsafeCategoryFolder`，
    而它由 `main.py:101` 在 `MainApp.__init__` 里直接调用（未包 try）→ **启动即崩**。
    修法：跳过该分类 + 记 ERROR 日志，其余分类照常初始化（可见的降级）。
    """

    def _bad_cat(self):
        return {"name": "恶意分类", "extensions": ["evil"], "folder": "..\\..\\evil"}

    def test_init_folders_skips_bad_category_and_keeps_others(self):
        cats = [self._bad_cat()] + [dict(c) for c in CATEGORIES]
        cfg = self.make_config(initialized=False, categories=cats)
        good_src = self.write_file(os.path.join(self.desktop, "report.doc"), "hi")
        bad_src = self.write_file(os.path.join(self.desktop, "x.evil"), "evil")

        # 不抛异常 = 应用能启动
        with self.assertLogs("file_manager", level="ERROR") as cm:
            result = file_manager.init_folders(cfg)

        # 坏分类被跳过：它的匹配文件留在桌面、没有被搬到任何地方
        self.assertEqual(result.skipped, 1)
        self.assertTrue(os.path.exists(bad_src), "坏分类匹配的文件不得被搬走")
        # 其余分类照常工作：目录都建好了、正常文件也搬进去了
        for c in CATEGORIES:
            self.assertTrue(
                os.path.isdir(os.path.join(self.storage, c["folder"])),
                f"正常分类 {c['name']} 的目录应被创建",
            )
        moved = os.path.join(self.storage, "办公文件", "report.doc")
        self.assertTrue(os.path.isfile(moved))
        self.assertFalse(os.path.exists(good_src))
        self.assertInsideTmp(moved)
        # 可见的错误记录
        joined = "\n".join(cm.output)
        self.assertIn("已跳过", joined)
        self.assertIn("恶意分类", joined)
        # 首次搬移照常落盘（坏分类不影响 initialized 置位）
        self.assertTrue(cfg["initialized"])
        self.assertTrue(os.path.exists(self.config_path))

    def test_init_folders_all_bad_categories_does_not_crash(self):
        cfg = self.make_config(
            initialized=False,
            categories=[self._bad_cat(), {"name": "x", "extensions": [], "folder": ""}],
        )
        with self.assertLogs("file_manager", level="ERROR"):
            result = file_manager.init_folders(cfg)  # 不抛异常
        self.assertEqual(result.skipped, 2)
        self.assertEqual(result.moved, 0)

    def test_init_folders_skips_non_string_folder(self):
        # "folder": 123 —— 以前 get_category_folder 会抛 TypeError（不是 UnsafeCategoryFolder）
        cfg = self.make_config(
            initialized=False,
            categories=[{"name": "数字", "extensions": ["doc"], "folder": 123}],
        )
        src = self.write_file(os.path.join(self.desktop, "a.doc"), "data")
        with self.assertLogs("file_manager", level="ERROR"):
            result = file_manager.init_folders(cfg)  # 不抛 TypeError
        self.assertEqual(result.skipped, 1)
        self.assertTrue(os.path.exists(src), "非字符串 folder 的分类应被跳过，文件留下")


# ── _move_matching_files ─────────────────────────────────

class TestMoveMatchingFiles(InitFoldersTestBase):

    def setUp(self):
        super().setUp()
        self.source = os.path.join(self.tmp, "source")
        self.target = os.path.join(self.tmp, "target")
        os.makedirs(self.source)
        os.makedirs(self.target)

    def test_moves_only_matching_extensions(self):
        doc = self.write_file(os.path.join(self.source, "a.doc"), "A")
        zipf = self.write_file(os.path.join(self.source, "b.zip"), "B")
        txt = self.write_file(os.path.join(self.source, "c.txt"), "C")

        file_manager._move_matching_files(self.source, self.target, ["doc"])

        self.assertTrue(os.path.isfile(os.path.join(self.target, "a.doc")))
        self.assertFalse(os.path.exists(doc))
        self.assertTrue(os.path.exists(zipf), "不匹配的 zip 应留下")
        self.assertTrue(os.path.exists(txt), "不匹配的 txt 应留下")

    def test_extension_match_is_case_insensitive_with_dot_prefix(self):
        self.write_file(os.path.join(self.source, "SHOUT.DOCX"), "S")
        file_manager._move_matching_files(self.source, self.target, [".docx"])
        self.assertTrue(os.path.isfile(os.path.join(self.target, "SHOUT.DOCX")))

    def test_skips_subdirectories(self):
        sub = os.path.join(self.source, "folder.zip")  # 名字像文件，其实是目录
        os.makedirs(sub)
        self.write_file(os.path.join(self.source, "real.zip"), "R")

        file_manager._move_matching_files(self.source, self.target, ["zip"])

        self.assertTrue(os.path.isdir(sub), "目录不应被搬走")
        self.assertTrue(os.path.isfile(os.path.join(self.target, "real.zip")))

    def test_name_conflict_renames_and_preserves_existing(self):
        existing = self.write_file(os.path.join(self.target, "a.doc"), "old")
        self.write_file(os.path.join(self.source, "a.doc"), "new")

        file_manager._move_matching_files(self.source, self.target, ["doc"])

        self.assertEqual(self.read_file(existing), "old")
        moved = os.path.join(self.target, "a(1).doc")
        self.assertTrue(os.path.isfile(moved))
        self.assertEqual(self.read_file(moved), "new")

    def test_empty_extensions_moves_nothing(self):
        src = self.write_file(os.path.join(self.source, "a.doc"), "A")
        file_manager._move_matching_files(self.source, self.target, [])
        self.assertTrue(os.path.exists(src))

    def test_no_matching_files_returns_zero_stats(self):
        self.write_file(os.path.join(self.source, "a.txt"), "A")
        result = file_manager._move_matching_files(self.source, self.target, ["doc"])
        self.assertEqual(result.moved, 0)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.errors, [])

    def test_move_failure_is_reported(self):
        src = self.write_file(os.path.join(self.source, "a.doc"), "keep")

        with mock.patch("file_manager.shutil.move", side_effect=OSError("boom")):
            with self.assertLogs("file_manager", level="WARNING") as cm:
                result = file_manager._move_matching_files(self.source, self.target, ["doc"])

        self.assertTrue(os.path.exists(src), "移动失败时源文件必须保留")
        # 新行为：失败被统计并带上原因，而不是静默吞掉
        self.assertEqual(result.moved, 0)
        self.assertEqual(result.failed, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], OSError)
        # AW-8：失败同时写进日志（不只靠调用方检查返回值）
        self.assertIn("boom", "\n".join(cm.output), "失败原因必须被记录")

    def test_listdir_failure_counted_as_failure_and_logged(self):
        # AW-8：旧写法 `return MoveStats(0, 0, [e])` 把「列不出目录」算成 0 失败，
        # 只看 failed 计数的调用方会漏掉。现在 failed=1，且记 WARNING。
        with mock.patch("file_manager.os.listdir", side_effect=OSError("no access")):
            with self.assertLogs("file_manager", level="WARNING") as cm:
                result = file_manager._move_matching_files(self.source, self.target, ["doc"])

        self.assertEqual(result.moved, 0)
        self.assertEqual(result.failed, 1, "列目录失败必须计入失败数，而不是 0")
        self.assertEqual(len(result.errors), 1)
        self.assertIn("no access", "\n".join(cm.output), "失败原因必须被记录")


# ── get_files_in_category ────────────────────────────────

class TestGetFilesInCategory(InitFoldersTestBase):

    def setUp(self):
        super().setUp()
        self.cat = {"name": "图片", "extensions": ["png"], "folder": "图片"}
        self.cfg = self.make_config(initialized=True)
        self.folder = os.path.join(self.storage, "图片")

    def test_missing_folder_returns_empty_list(self):
        self.assertEqual(file_manager.get_files_in_category(self.cfg, self.cat), [])

    def test_empty_folder_returns_empty_list(self):
        os.makedirs(self.folder)
        self.assertEqual(file_manager.get_files_in_category(self.cfg, self.cat), [])

    def test_lists_files_and_subfolders(self):
        self.write_file(os.path.join(self.folder, "a.png"), "A")
        self.write_file(os.path.join(self.folder, "b.png"), "B")
        os.makedirs(os.path.join(self.folder, "project"))

        got = file_manager.get_files_in_category(self.cfg, self.cat)

        names = {name for _full, name, _mtime in got}
        self.assertEqual(names, {"a.png", "b.png", "project"})
        for full, name, mtime in got:
            self.assertEqual(os.path.dirname(full), self.folder)
            self.assertEqual(os.path.basename(full), name)
            self.assertInsideTmp(full)

    def test_sorted_by_mtime_descending(self):
        old = self.write_file(os.path.join(self.folder, "old.png"), "O")
        new = self.write_file(os.path.join(self.folder, "new.png"), "N")
        os.utime(old, (1_600_000_000, 1_600_000_000))
        os.utime(new, (1_700_000_000, 1_700_000_000))

        got = file_manager.get_files_in_category(self.cfg, self.cat)

        self.assertEqual([name for _f, name, _m in got], ["new.png", "old.png"])

    def test_uses_folder_field_not_name(self):
        cat = {"name": "自定义", "extensions": [], "folder": "pics"}
        self.write_file(os.path.join(self.storage, "pics", "x.png"), "X")
        got = file_manager.get_files_in_category(self.cfg, cat)
        self.assertEqual([name for _f, name, _m in got], ["x.png"])

    def test_listdir_oserror_returns_empty_list(self):
        os.makedirs(self.folder)
        with mock.patch("file_manager.os.listdir", side_effect=OSError("nope")):
            got = file_manager.get_files_in_category(self.cfg, self.cat)
        self.assertEqual(got, [])

    def test_listdir_oserror_is_logged(self):
        # AW-8：旧实现 `except OSError: return []` 静默吞掉——GUI 只看到「空分类」，
        # 完全不知道目录读不出来。现在返回 [] 不变（契约），但必须记 WARNING。
        os.makedirs(self.folder)
        with mock.patch("file_manager.os.listdir", side_effect=OSError("no access")):
            with self.assertLogs("file_manager", level="WARNING") as cm:
                got = file_manager.get_files_in_category(self.cfg, self.cat)

        self.assertEqual(got, [], "公开契约不变：仍返回 []，GUI 不崩")
        joined = "\n".join(cm.output)
        self.assertIn("no access", joined, "失败原因必须被记录")
        self.assertIn(self.folder, joined, "必须指出是哪个分类目录读不出来")


# ── _move_no_clobber（结构化结果 + 不覆盖）─────────────────

class TestMoveNoClobber(InitFoldersTestBase):

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, "target")
        os.makedirs(self.folder)

    def test_moves_file_and_returns_success_result(self):
        src = self.write_file(os.path.join(self.tmp, "a.doc"), "NEW")
        result = file_manager._move_no_clobber(src, self.folder, "a.doc")
        self.assertTrue(result.ok)
        self.assertEqual(result.path, os.path.join(self.folder, "a.doc"))
        self.assertIsNone(result.error)
        self.assertFalse(os.path.exists(src))
        self.assertEqual(self.read_file(result.path), "NEW")

    def test_conflict_renames_and_preserves_existing(self):
        existing = self.write_file(os.path.join(self.folder, "a.doc"), "OLD")
        src = self.write_file(os.path.join(self.tmp, "a.doc"), "NEW")

        result = file_manager._move_no_clobber(src, self.folder, "a.doc")

        self.assertTrue(result.ok)
        self.assertEqual(os.path.basename(result.path), "a(1).doc")
        self.assertEqual(self.read_file(existing), "OLD", "已存在的同名文件不得被覆盖")
        self.assertEqual(self.read_file(result.path), "NEW")

    def test_returns_failure_result_on_move_error(self):
        src = self.write_file(os.path.join(self.tmp, "a.doc"), "keep")

        with mock.patch("file_manager.shutil.move", side_effect=OSError("boom")):
            result = file_manager._move_no_clobber(src, self.folder, "a.doc")

        self.assertFalse(result.ok, "移动失败必须返回失败结果，而不是静默 None")
        self.assertIsNone(result.path)
        self.assertIsInstance(result.error, OSError)
        self.assertTrue(os.path.exists(src), "失败时源文件必须保留")
        # 占位文件必须被清理，不能留下空文件
        self.assertEqual(os.listdir(self.folder), [])

    def test_returns_failure_result_when_target_dir_missing(self):
        src = self.write_file(os.path.join(self.tmp, "a.doc"), "keep")
        missing = os.path.join(self.tmp, "no-such-dir")

        result = file_manager._move_no_clobber(src, missing, "a.doc")

        self.assertFalse(result.ok)
        self.assertIsInstance(result.error, OSError)
        self.assertTrue(os.path.exists(src))

    def test_moves_directory_without_clobbering(self):
        src = os.path.join(self.tmp, "proj")
        self.write_file(os.path.join(src, "in.txt"), "IN")

        result = file_manager._move_no_clobber(src, self.folder, "proj")

        self.assertTrue(result.ok)
        self.assertTrue(os.path.isfile(os.path.join(result.path, "in.txt")))
        self.assertFalse(os.path.exists(src))

    def test_directory_conflict_renames(self):
        os.makedirs(os.path.join(self.folder, "proj"))
        src = os.path.join(self.tmp, "proj")
        self.write_file(os.path.join(src, "in.txt"), "IN")

        result = file_manager._move_no_clobber(src, self.folder, "proj")

        self.assertTrue(result.ok)
        self.assertEqual(os.path.basename(result.path), "proj(1)")
        self.assertTrue(os.path.isdir(os.path.join(self.folder, "proj")))


# ── TOCTOU 竞态回归 ──────────────────────────────────────
#
# 旧实现「_resolve_conflict 先查存在 → shutil.move 再落盘」之间存在竞态窗口：
# 别的进程在这中间抢占同名路径时，shutil.move 会**静默覆盖**它（数据丢失）。
# 新实现原子占用目标名，必须保留抢占者写入的内容。

class TestResolveConflictRace(InitFoldersTestBase):

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, "target")
        os.makedirs(self.folder)

    def _make_racer(self):
        """真实解析 + 只抢跑一次：在解析出的路径处写入一个「别人创建的文件」。"""
        real = file_manager._resolve_conflict
        state = {"fired": False}

        def racy(folder, filename):
            dest = real(folder, filename)
            if not state["fired"]:
                state["fired"] = True
                with open(dest, "w", encoding="utf-8") as f:
                    f.write("RACER")
            return dest

        return racy

    def test_race_does_not_clobber_newcomer_file(self):
        src = self.write_file(os.path.join(self.tmp, "a.doc"), "NEW")

        with mock.patch(
            "file_manager._resolve_conflict", side_effect=self._make_racer()
        ):
            result = file_manager._move_no_clobber(src, self.folder, "a.doc")

        self.assertTrue(result.ok)
        # 抢跑者写进去的内容必须还在（旧实现会被覆盖成 "NEW"）
        self.assertEqual(self.read_file(os.path.join(self.folder, "a.doc")), "RACER")
        self.assertEqual(os.path.basename(result.path), "a(1).doc")
        self.assertEqual(self.read_file(result.path), "NEW")

    def test_categorize_file_race_does_not_clobber(self):
        cfg = self.make_config(initialized=True)
        folder = os.path.join(self.storage, "办公文件")
        os.makedirs(folder, exist_ok=True)
        src = self.write_file(os.path.join(self.desktop, "a.doc"), "NEW")

        with mock.patch(
            "file_manager._resolve_conflict", side_effect=self._make_racer()
        ):
            name, dest = file_manager.categorize_file(src, cfg)

        self.assertEqual(name, "办公文件")
        self.assertEqual(self.read_file(os.path.join(folder, "a.doc")), "RACER")
        self.assertEqual(os.path.basename(dest), "a(1).doc")
        self.assertEqual(self.read_file(dest), "NEW")


# ── 跨盘目录搬移（EXDEV → copytree 分支）──────────────────
#
# 所有目录用例默认都在同一个 tempdir（同盘），只走 os.rename 分支；
# 跨盘正确性此前**完全靠 shutil.copytree 的实现细节兜底、零回归保护**。
# 这里用 mock.patch 让 os.rename 抛 OSError(EXDEV) 强制走 copytree 分支。

def _exdev(*_args, **_kwargs):
    """模拟跨盘符：os.rename 抛 EXDEV。"""
    raise OSError(errno.EXDEV, "Invalid cross-device link")


class TestCrossDriveDirectoryMove(InitFoldersTestBase):

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, "target")
        os.makedirs(self.folder)

    def test_same_drive_dir_move_uses_rename_not_copytree(self):
        """同盘时走 os.rename，**不应**碰 copytree（对照组）。"""
        src = os.path.join(self.tmp, "proj")
        self.write_file(os.path.join(src, "in.txt"), "IN")

        with mock.patch(
            "file_manager.shutil.copytree", wraps=shutil.copytree
        ) as cp:
            result = file_manager._move_no_clobber(src, self.folder, "proj")

        self.assertTrue(result.ok)
        self.assertFalse(cp.called, "同盘搬移不该退回 copytree")

    def test_cross_drive_dir_move_uses_copytree(self):
        """EXDEV 时退回 copytree，且搬移结果正确、源目录被删除。"""
        src = os.path.join(self.tmp, "proj")
        self.write_file(os.path.join(src, "in.txt"), "IN")

        with mock.patch("file_manager.os.rename", side_effect=_exdev), \
             mock.patch(
                 "file_manager.shutil.copytree", wraps=shutil.copytree
             ) as cp:
            result = file_manager._move_no_clobber(src, self.folder, "proj")

        self.assertTrue(cp.called, "EXDEV 时必须走 copytree 分支")
        self.assertTrue(result.ok)
        self.assertEqual(os.path.basename(result.path), "proj")
        self.assertTrue(os.path.isfile(os.path.join(result.path, "in.txt")))
        self.assertEqual(self.read_file(os.path.join(result.path, "in.txt")), "IN")
        self.assertFalse(os.path.exists(src), "跨盘搬移后源目录应被删除")

    def test_cross_drive_dir_conflict_renames_and_preserves_existing(self):
        """跨盘 + 目标已占：改名重试，绝不覆盖已存在的同名目录。"""
        existing = os.path.join(self.folder, "proj")
        self.write_file(os.path.join(existing, "old.txt"), "OLD")
        src = os.path.join(self.tmp, "proj")
        self.write_file(os.path.join(src, "new.txt"), "NEW")

        with mock.patch("file_manager.os.rename", side_effect=_exdev):
            result = file_manager._move_no_clobber(src, self.folder, "proj")

        self.assertTrue(result.ok)
        self.assertEqual(os.path.basename(result.path), "proj(1)")
        # 已存在的同名目录必须原地不动，新目录也不得嵌套进去
        self.assertEqual(self.read_file(os.path.join(existing, "old.txt")), "OLD")
        self.assertFalse(os.path.exists(os.path.join(existing, "new.txt")))
        self.assertEqual(self.read_file(os.path.join(result.path, "new.txt")), "NEW")
        self.assertFalse(os.path.exists(src))

    def test_cross_drive_copytree_collision_retries_without_clobber(self):
        """
        逼 copytree 自己的 makedirs 撞上已被占用的目标名（FileExistsError）：
        必须换名重试，绝不覆盖抢占者。
        """
        existing = os.path.join(self.folder, "proj")
        self.write_file(os.path.join(existing, "old.txt"), "OLD")
        src = os.path.join(self.tmp, "proj")
        self.write_file(os.path.join(src, "new.txt"), "NEW")

        real = file_manager._resolve_conflict
        state = {"fired": False}

        def racy(folder, filename):
            dest = real(folder, filename)
            if not state["fired"]:
                state["fired"] = True
                # 硬指向已占用的 proj，让 copytree 的 makedirs 抛 FileExistsError
                return os.path.join(folder, filename)
            return dest

        with mock.patch("file_manager.os.rename", side_effect=_exdev), \
             mock.patch("file_manager._resolve_conflict", side_effect=racy):
            result = file_manager._move_no_clobber(src, self.folder, "proj")

        self.assertTrue(result.ok, "撞上占用目标名后应换名重试而不是失败")
        self.assertEqual(os.path.basename(result.path), "proj(1)")
        self.assertEqual(self.read_file(os.path.join(existing, "old.txt")), "OLD")
        self.assertFalse(os.path.exists(os.path.join(existing, "new.txt")))


# ── 半拷贝残留清理（copytree / copy2 中途失败）────────────
#
# 旧实现：文件路径的 _release_placeholder 只在占位**大小为 0** 时才删，
# 跨盘 copy2 已写入部分内容（非空）时会残留半截垃圾；目录路径**完全没有**
# 清理机制，copytree 中途失败会在存储目录里留下一个半拷贝目录。

class TestPartialMoveCleanup(InitFoldersTestBase):

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, "target")
        os.makedirs(self.folder)

    def test_cross_drive_copytree_failure_leaves_no_partial_dir(self):
        """copytree 拷了一半失败 → 半拷贝目录必须被清掉，源目录完好。"""
        src = os.path.join(self.tmp, "proj")
        self.write_file(os.path.join(src, "in.txt"), "IN")

        def boom(_src, dst, *_a, **_k):
            # dest 现在由 _move_dir_no_clobber 自己先原子占用（所有权证据），
            # copytree 收到的是已存在的空目录 → 这里用 exist_ok 忠实模拟「拷到一半失败」
            os.makedirs(dst, exist_ok=True)
            self.write_file(os.path.join(dst, "half.txt"), "HALF")
            raise OSError("disk full")

        with mock.patch("file_manager.os.rename", side_effect=_exdev), \
             mock.patch("file_manager.shutil.copytree", side_effect=boom):
            result = file_manager._move_no_clobber(src, self.folder, "proj")

        self.assertFalse(result.ok)
        self.assertIsInstance(result.error, OSError)
        self.assertEqual(os.listdir(self.folder), [], "半拷贝残留必须清理干净")
        self.assertTrue(os.path.isfile(os.path.join(src, "in.txt")), "源目录必须完好")
        self.assertEqual(self.read_file(os.path.join(src, "in.txt")), "IN")

    def test_file_copy_failure_leaves_no_nonempty_placeholder(self):
        """跨盘 copy2 已写入部分内容后失败 → 非空半截占位也必须清掉。"""
        src = self.write_file(os.path.join(self.tmp, "a.doc"), "NEW")

        def boom(_src, dst, *_a, **_k):
            self.write_file(dst, "PARTIAL")  # 非空占位（旧实现会漏网）
            raise OSError("disk full")

        with mock.patch("file_manager.shutil.move", side_effect=boom):
            result = file_manager._move_no_clobber(src, self.folder, "a.doc")

        self.assertFalse(result.ok)
        self.assertIsInstance(result.error, OSError)
        self.assertEqual(os.listdir(self.folder), [], "非空半截占位必须清理干净")
        self.assertTrue(os.path.exists(src))
        self.assertEqual(self.read_file(src), "NEW")

    def test_leftover_is_reported_when_cleanup_fails(self):
        """清理本身失败时，残留路径必须上报到结果里，供调用方提示用户手工清。"""
        src = os.path.join(self.tmp, "proj")
        self.write_file(os.path.join(src, "in.txt"), "IN")

        def boom(_src, dst, *_a, **_k):
            os.makedirs(dst, exist_ok=True)
            raise OSError("disk full")

        with mock.patch("file_manager.os.rename", side_effect=_exdev), \
             mock.patch("file_manager.shutil.copytree", side_effect=boom), \
             mock.patch("file_manager.shutil.rmtree", lambda *_a, **_k: None):
            result = file_manager._move_no_clobber(src, self.folder, "proj")

        self.assertFalse(result.ok)
        residual = getattr(result.error, "residual", None)
        self.assertEqual(
            residual, os.path.join(self.folder, "proj"),
            "清理失败时必须把残留路径上报，而不是悄悄留下半成品",
        )


# ── 失败清理的所有权校验（AW-17）────────────────────────
#
# 旧实现把「dest 已存在」与「copytree 起步失败」混为一谈：`_move_dir_no_clobber`
# 的 `except BaseException` 分支**无条件 rmtree(dest)**。但 copytree 的第一步是
# `os.scandir(src)`——若 src 在「rename 抛 EXDEV」与「copytree」之间被并发删除，
# copytree 会在创建 dest **之前**就失败，此时 dest 可能是别人/用户并发创建的目录，
# 无条件清理就会**删掉非自己创建的目录**（AW-17 复查实测：用户数据被删）。
# 修复后：只有 `os.makedirs(dest)` 成功（=拿到所有权证据）之后的失败才清理。

class TestCleanupOwnership(InitFoldersTestBase):

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, "target")
        os.makedirs(self.folder)

    def test_compound_race_does_not_delete_foreign_dest(self):
        """
        复现 AW-16 复查实测的复合竞态（用**真实** copytree）：
          (1) os.rename 抛 EXDEV（Windows 语义下意味着当时 dest 不存在）；
          (2) dest 在 rename 与 copytree 之间被并发创建（这里是用户的目录）；
          (3) src 在该窗口被并发删除 → 真实 copytree 会在 `os.makedirs(dst)`
              **之前**的 `os.scandir(src)` 就失败。
        旧实现此时会无条件 rmtree(dest)，把用户目录连内容一起删掉。
        修复后必须：用户目录一字节没少 + 失败被如实上报。
        """
        src = os.path.join(self.tmp, "victim")
        self.write_file(os.path.join(src, "payload.txt"), "SRC")
        dest = os.path.join(self.folder, "victim")
        user_file = os.path.join(dest, "USERDATA.txt")

        def racy_rename(src_arg, _dest_arg):
            # 模拟「rename 抛 EXDEV 之后、copytree 之前」的并发窗口：
            # dest 被并发创建成用户的目录，src 被并发删除，然后才抛 EXDEV。
            os.makedirs(dest, exist_ok=True)
            if not os.path.exists(user_file):
                with open(user_file, "w", encoding="utf-8") as f:
                    f.write("PRECIOUS")
            if os.path.exists(src_arg):
                shutil.rmtree(src_arg)
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        with mock.patch("file_manager.os.rename", side_effect=racy_rename):
            result = file_manager._move_no_clobber(src, self.folder, "victim")

        # 1) 用户目录必须原封不动（旧实现会 rmtree 掉它）
        self.assertTrue(os.path.isdir(dest), "用户目录被误删了！")
        self.assertTrue(os.path.isfile(user_file), "用户数据文件被删了！")
        self.assertEqual(self.read_file(user_file), "PRECIOUS", "用户数据被删/篡改")
        # 2) 失败必须被如实上报，而不是假装成功
        self.assertFalse(result.ok, "复合竞态下应返回失败结果")
        self.assertIsInstance(result.error, OSError)

    def test_foreign_dest_not_deleted_when_copytree_fails_before_makedirs(self):
        """
        更直接的所有权对照：把解析逼到**已预存的用户目录**上，copytree 又在
        `os.makedirs(dst)` 之前的 `os.scandir(src)` 就失败（真实 copytree 的起步
        失败形态）。修复后只允许清理我们自己建的目录 → 这个预存目录必须原样保留
        （旧实现会无条件 rmtree 掉它）。
        """
        dest = os.path.join(self.folder, "victim")
        self.write_file(os.path.join(dest, "USERDATA.txt"), "PRECIOUS")
        src = os.path.join(self.tmp, "victim")
        self.write_file(os.path.join(src, "in.txt"), "IN")

        def fail_before_makedirs(_src, _dst, *_a, **_k):
            # 忠实模拟真实 copytree 的「第一步 os.scandir(src) 就失败」：
            # 此时 dest 还没被创建（这里的 dest 是别人预存的）
            raise FileNotFoundError(errno.ENOENT, "src gone")

        real = file_manager._resolve_conflict
        state = {"fired": False}

        def racy(folder, filename):
            if not state["fired"]:
                state["fired"] = True
                # 硬指向已预存的 victim，让 dest 就是那个「别人的目录」
                return os.path.join(folder, filename)
            return real(folder, filename)

        with mock.patch("file_manager.os.rename", side_effect=_exdev), \
             mock.patch(
                 "file_manager.shutil.copytree", side_effect=fail_before_makedirs
             ), \
             mock.patch("file_manager._resolve_conflict", side_effect=racy):
            result = file_manager._move_no_clobber(src, self.folder, "victim")

        self.assertTrue(os.path.isdir(dest), "预存的用户目录不得被删")
        self.assertEqual(self.read_file(os.path.join(dest, "USERDATA.txt")), "PRECIOUS")
        self.assertFalse(result.ok)


# ── 拖拽/归类路径上报失败原因（AW-17 顺手修的既有缺陷）───
#
# 旧实现里 categorize_file / move_into_category 只看 result.ok，失败就
# `return None, None`，于是 `MoveResult.error`（尤其 `PartialMoveError.residual`
# 半成品路径）被静默吞掉——「有个半成品要手工清」这件事用户永远看不到。

class TestDragPathReportsFailure(InitFoldersTestBase):

    def test_categorize_file_logs_move_failure(self):
        cfg = self.make_config(initialized=True)
        src = self.write_file(os.path.join(self.desktop, "a.doc"), "NEW")
        residual = os.path.join(self.storage, "办公文件", "a.doc")

        # 让「占位已建、move 失败、清理也失败」真的发生 → PartialMoveError 带 residual
        with mock.patch("file_manager.shutil.move", side_effect=OSError("boom")), \
             mock.patch(
                 "file_manager._cleanup_partial",
                 side_effect=lambda dest, is_dir: dest,
             ):
            with self.assertLogs("file_manager", level="WARNING") as cm:
                result = file_manager.categorize_file(src, cfg)

        self.assertEqual(result, (None, None), "公开契约仍是 2 元组 (None, None)")
        self.assertTrue(os.path.exists(src), "失败时源文件必须保留")
        joined = "\n".join(cm.output)
        self.assertIn("boom", joined, "失败原因必须被记录")
        self.assertIn(residual, joined, "半成品残留路径必须被上报，不能静默吞掉")

    def test_move_into_category_logs_residual(self):
        cfg = self.make_config(initialized=True)
        cat = {"name": "图片", "extensions": [], "folder": "图片"}
        src_dir = os.path.join(self.desktop, "proj")
        self.write_file(os.path.join(src_dir, "in.txt"), "IN")
        residual = os.path.join(self.storage, "图片", "proj")

        def boom(_src, dst, *_a, **_k):
            os.makedirs(dst, exist_ok=True)
            raise OSError("disk full")

        with mock.patch("file_manager.os.rename", side_effect=_exdev), \
             mock.patch("file_manager.shutil.copytree", side_effect=boom), \
             mock.patch("file_manager.shutil.rmtree", lambda *_a, **_k: None):
            with self.assertLogs("file_manager", level="WARNING") as cm:
                result = file_manager.move_into_category(cfg, cat, src_dir)

        self.assertEqual(result, (None, None))
        joined = "\n".join(cm.output)
        self.assertIn("disk full", joined, "失败原因必须被记录")
        self.assertIn(residual, joined, "残留路径必须上报到拖拽路径的日志里")


if __name__ == "__main__":
    unittest.main()
