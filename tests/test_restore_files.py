"""
restore_files.py 的单元测试（标准库 unittest，零新依赖）。

数据安全红线：本脚本会**真实移动文件**。所有用例都在
`tempfile.TemporaryDirectory()` 里造目录，并 `mock.patch("config.CONFIG_PATH", 临时路径)`
打桩配置路径；端到端用例还额外把 `os.path.expanduser` 重定向到临时目录，
**即使修复被撤掉也不会碰到真实 `~/Desktop`**（回退路径只会落在临时目录里）。
不导入任何 GUI 模块，不运行 `main.py`。

运行：python -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import config  # noqa: E402
import restore_files  # noqa: E402


class RestoreTestBase(unittest.TestCase):
    """把 CONFIG_PATH 打桩到临时目录，绝不动仓库根目录的 config.json。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.config_path = os.path.join(self.tmp, "config.json")

        patcher = mock.patch("config.CONFIG_PATH", self.config_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_config(self, cfg):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)


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


if __name__ == "__main__":
    unittest.main()
