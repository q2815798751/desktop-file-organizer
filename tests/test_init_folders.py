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
import os
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
            result = file_manager._move_matching_files(self.source, self.target, ["doc"])

        self.assertTrue(os.path.exists(src), "移动失败时源文件必须保留")
        # 新行为：失败被统计并带上原因，而不是静默吞掉
        self.assertEqual(result.moved, 0)
        self.assertEqual(result.failed, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], OSError)


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


if __name__ == "__main__":
    unittest.main()
