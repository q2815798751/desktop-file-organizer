"""
file_manager.py 纯逻辑单元测试（标准库 unittest，零新依赖）。

数据安全：所有涉及移动/删除/重命名的用例都在 tempfile.TemporaryDirectory()
里造目录，并通过 config 字典（以及 unittest.mock.patch）把 desktop_path /
storage_path 指向临时目录——**绝不触碰真实桌面或真实用户目录**。
GUI 模块（dashboard.py / desktop_panel.py）不导入。

运行：python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

# 让测试模块无论从哪个工作目录运行都能 import 到仓库根目录下的 file_manager
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import file_manager  # noqa: E402


# 与 config.DEFAULT_CONFIG 保持一致的精简分类表（仅测试用）
CATEGORIES = [
    {"name": "办公文件", "extensions": ["doc", "docx", "pdf"], "folder": "办公文件"},
    {"name": "压缩包", "extensions": ["zip", "rar"], "folder": "压缩包"},
    {"name": "图片", "extensions": ["png", "jpg"], "folder": "图片"},
    {"name": "其他", "extensions": [], "folder": "其他"},
]


class TempDirsMixin:
    """在临时目录里造一个「假桌面」和一个「假存储根」，用完自动清理。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.desktop = os.path.join(self.tmp, "Desktop")
        self.storage = os.path.join(self.tmp, "storage")
        os.makedirs(self.desktop)
        os.makedirs(self.storage)

    def make_config(self, categories=None):
        return {
            "desktop_path": self.desktop,
            "storage_path": self.storage,
            "categories": categories if categories is not None else [
                dict(c) for c in CATEGORIES
            ],
        }

    # 便捷断言：确认路径落在临时目录内，防止用例误伤真实目录
    def assertInsideTmp(self, path):
        self.assertTrue(
            os.path.abspath(path).startswith(os.path.abspath(self.tmp) + os.sep),
            f"路径 {path!r} 不在临时目录 {self.tmp!r} 内",
        )

    def write_file(self, path, content="x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def read_file(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


# ── get_desktop_path ─────────────────────────────────────

class TestGetDesktopPath(TempDirsMixin, unittest.TestCase):

    def test_returns_configured_desktop_when_it_exists(self):
        cfg = self.make_config()
        self.assertEqual(file_manager.get_desktop_path(cfg), self.desktop)

    def test_falls_back_when_empty(self):
        cfg = self.make_config()
        cfg["desktop_path"] = ""
        with mock.patch("file_manager.os.path.expanduser", return_value=self.tmp):
            got = file_manager.get_desktop_path(cfg)
        self.assertEqual(got, os.path.join(self.tmp, "Desktop"))
        self.assertInsideTmp(got)

    def test_falls_back_when_path_does_not_exist(self):
        cfg = self.make_config()
        cfg["desktop_path"] = os.path.join(self.tmp, "nope")
        with mock.patch("file_manager.os.path.expanduser", return_value=self.tmp):
            got = file_manager.get_desktop_path(cfg)
        self.assertEqual(got, os.path.join(self.tmp, "Desktop"))

    def test_falls_back_when_path_is_a_file_not_a_dir(self):
        cfg = self.make_config()
        f = self.write_file(os.path.join(self.tmp, "notadir"))
        cfg["desktop_path"] = f
        with mock.patch("file_manager.os.path.expanduser", return_value=self.tmp):
            got = file_manager.get_desktop_path(cfg)
        self.assertEqual(got, os.path.join(self.tmp, "Desktop"))

    def test_falls_back_when_key_missing(self):
        cfg = self.make_config()
        del cfg["desktop_path"]
        with mock.patch("file_manager.os.path.expanduser", return_value=self.tmp):
            got = file_manager.get_desktop_path(cfg)
        self.assertEqual(got, os.path.join(self.tmp, "Desktop"))


# ── get_storage_root ─────────────────────────────────────

class TestGetStorageRoot(TempDirsMixin, unittest.TestCase):

    def test_returns_configured_storage_path(self):
        cfg = self.make_config()
        self.assertEqual(file_manager.get_storage_root(cfg), self.storage)

    def test_default_when_empty(self):
        cfg = self.make_config()
        cfg["storage_path"] = ""
        with mock.patch("file_manager.os.path.expanduser", return_value=self.tmp):
            got = file_manager.get_storage_root(cfg)
        expected = os.path.join(
            self.tmp, "Documents", file_manager.DEFAULT_STORAGE_NAME
        )
        self.assertEqual(got, expected)

    def test_default_when_key_missing(self):
        cfg = self.make_config()
        del cfg["storage_path"]
        with mock.patch("file_manager.os.path.expanduser", return_value=self.tmp):
            got = file_manager.get_storage_root(cfg)
        self.assertEqual(
            got,
            os.path.join(self.tmp, "Documents", file_manager.DEFAULT_STORAGE_NAME),
        )


# ── get_category_folder ──────────────────────────────────

class TestGetCategoryFolder(TempDirsMixin, unittest.TestCase):

    def test_uses_folder_field(self):
        cfg = self.make_config()
        cat = {"name": "图片", "extensions": [], "folder": "my_pics"}
        self.assertEqual(
            file_manager.get_category_folder(cfg, cat),
            os.path.join(self.storage, "my_pics"),
        )

    def test_falls_back_to_name_when_folder_missing(self):
        cfg = self.make_config()
        cat = {"name": "图片", "extensions": []}
        self.assertEqual(
            file_manager.get_category_folder(cfg, cat),
            os.path.join(self.storage, "图片"),
        )

    def test_folder_is_under_storage_root(self):
        cfg = self.make_config()
        folder = file_manager.get_category_folder(cfg, CATEGORIES[0])
        self.assertEqual(os.path.dirname(folder), self.storage)


# ── AW-3：folder 字段越界必须被拒绝 ──────────────────────

class TestCategoryFolderSafety(TempDirsMixin, unittest.TestCase):
    """folder 来自用户自由文本，越界（逃出存储根）必须**拒绝**而不是静默兜底。"""

    def _cat(self, folder):
        return {"name": "恶意分类", "extensions": ["evil"], "folder": folder}

    def assertRejected(self, folder):
        cfg = self.make_config()
        with self.assertRaises(file_manager.UnsafeCategoryFolder):
            file_manager.get_category_folder(cfg, self._cat(folder))

    # —— 被拒绝的三种形态 ——

    def test_rejects_windows_parent_traversal(self):
        # 任务点名的 `..\..\evil`
        self.assertRejected("..\\..\\evil")

    def test_rejects_posix_parent_traversal(self):
        self.assertRejected("../../evil")

    def test_rejects_absolute_posix_path(self):
        self.assertRejected(os.path.join(os.path.abspath(os.sep), "evil_abs"))

    def test_rejects_absolute_windows_path(self):
        self.assertRejected("C:\\Windows\\evil")

    def test_rejects_rooted_backslash_path(self):
        # 以分隔符开头（Windows 上是「当前盘根」）也算绝对路径
        self.assertRejected("\\evil")

    def test_rejects_nested_parent_traversal(self):
        # 含 `..` 的嵌套路径
        self.assertRejected("a\\..\\..\\evil")
        self.assertRejected("sub/../../evil")

    def test_rejects_dotdot_even_if_it_resolves_back_inside(self):
        # 绕回存储根内也不放行：这种写法只可能是有意为之
        self.assertRejected("sub/../evil")

    def test_rejects_dot_alone(self):
        # 解析后等于存储根本身 → 不是「子文件夹」
        self.assertRejected(".")

    def test_rejects_empty_folder(self):
        self.assertRejected("")
        self.assertRejected("   ")

    def test_rejects_when_missing_folder_falls_back_to_malicious_name(self):
        # folder 缺省时回退到 name，name 本身越界同样要拒
        cfg = self.make_config()
        cat = {"name": "..\\..\\evil", "extensions": []}
        with self.assertRaises(file_manager.UnsafeCategoryFolder):
            file_manager.get_category_folder(cfg, cat)

    def test_rejection_message_is_explicit(self):
        cfg = self.make_config()
        with self.assertRaises(file_manager.UnsafeCategoryFolder) as ctx:
            file_manager.get_category_folder(cfg, self._cat("..\\..\\evil"))
        self.assertIn("不安全", str(ctx.exception))

    # —— 正常 folder 仍能解析 ——

    def test_normal_folder_still_resolves(self):
        cfg = self.make_config()
        cat = {"name": "图片", "extensions": [], "folder": "pics"}
        self.assertEqual(
            file_manager.get_category_folder(cfg, cat),
            os.path.join(self.storage, "pics"),
        )

    def test_nested_folder_without_dotdot_still_resolves(self):
        cfg = self.make_config()
        cat = {"name": "x", "extensions": [], "folder": "sub/deeper"}
        got = file_manager.get_category_folder(cfg, cat)
        self.assertEqual(
            os.path.normpath(got),
            os.path.normpath(os.path.join(self.storage, "sub", "deeper")),
        )
        self.assertInsideTmp(got)

    def test_default_categories_still_resolve(self):
        cfg = self.make_config()
        for cat in CATEGORIES:
            got = file_manager.get_category_folder(cfg, cat)
            self.assertEqual(os.path.dirname(got), self.storage)
            self.assertInsideTmp(got)

    # —— 纯函数本身（GUI 直接调用它做校验）——

    def test_pure_function_returns_none_for_safe_name(self):
        self.assertIsNone(file_manager.category_folder_error(self.storage, "pics"))
        self.assertIsNone(
            file_manager.category_folder_error(self.storage, "sub/deeper")
        )

    def test_pure_function_returns_message_for_unsafe_name(self):
        for bad in ["..\\..\\evil", "../../evil", "C:\\Windows", "/etc", "", "."]:
            err = file_manager.category_folder_error(self.storage, bad)
            self.assertIsNotNone(err, f"{bad!r} 应被判为不安全")
            self.assertTrue(err.strip())


# ── _resolve_conflict ────────────────────────────────────

class TestResolveConflict(TempDirsMixin, unittest.TestCase):

    def test_no_conflict_returns_original_path(self):
        got = file_manager._resolve_conflict(self.desktop, "a.txt")
        self.assertEqual(got, os.path.join(self.desktop, "a.txt"))

    def test_single_conflict_renames_with_counter(self):
        self.write_file(os.path.join(self.desktop, "a.txt"))
        got = file_manager._resolve_conflict(self.desktop, "a.txt")
        self.assertEqual(got, os.path.join(self.desktop, "a(1).txt"))

    def test_multiple_conflicts_increment_counter(self):
        self.write_file(os.path.join(self.desktop, "a.txt"))
        self.write_file(os.path.join(self.desktop, "a(1).txt"))
        got = file_manager._resolve_conflict(self.desktop, "a.txt")
        self.assertEqual(got, os.path.join(self.desktop, "a(2).txt"))

    def test_extension_is_preserved(self):
        self.write_file(os.path.join(self.desktop, "报告.docx"))
        got = file_manager._resolve_conflict(self.desktop, "报告.docx")
        self.assertEqual(got, os.path.join(self.desktop, "报告(1).docx"))

    def test_file_without_extension(self):
        self.write_file(os.path.join(self.desktop, "README"))
        got = file_manager._resolve_conflict(self.desktop, "README")
        self.assertEqual(got, os.path.join(self.desktop, "README(1)"))

    def test_result_is_inside_folder(self):
        self.write_file(os.path.join(self.desktop, "a.txt"))
        got = file_manager._resolve_conflict(self.desktop, "a.txt")
        self.assertEqual(os.path.dirname(got), self.desktop)


# ── categorize_file ──────────────────────────────────────

class TestCategorizeFile(TempDirsMixin, unittest.TestCase):

    def test_moves_matching_file_into_category(self):
        cfg = self.make_config()
        src = self.write_file(os.path.join(self.desktop, "report.doc"), "hi")
        name, dest = file_manager.categorize_file(src, cfg)
        self.assertEqual(name, "办公文件")
        self.assertTrue(os.path.isfile(dest))
        self.assertFalse(os.path.exists(src))
        self.assertEqual(os.path.dirname(dest), os.path.join(self.storage, "办公文件"))
        self.assertInsideTmp(dest)

    def test_returns_none_for_unknown_extension(self):
        cfg = self.make_config()
        src = self.write_file(os.path.join(self.desktop, "note.txt"))
        self.assertEqual(file_manager.categorize_file(src, cfg), (None, None))
        self.assertTrue(os.path.exists(src), "不匹配的文件不应被移动")

    def test_returns_none_for_nonexistent_file(self):
        cfg = self.make_config()
        ghost = os.path.join(self.desktop, "ghost.doc")
        self.assertEqual(file_manager.categorize_file(ghost, cfg), (None, None))

    def test_ignores_file_inside_subfolder(self):
        cfg = self.make_config()
        src = self.write_file(os.path.join(self.desktop, "sub", "deep.doc"))
        self.assertEqual(file_manager.categorize_file(src, cfg), (None, None))
        self.assertTrue(os.path.exists(src))

    def test_extension_match_is_case_insensitive(self):
        cfg = self.make_config()
        src = self.write_file(os.path.join(self.desktop, "SHOUT.DOCX"))
        name, dest = file_manager.categorize_file(src, cfg)
        self.assertEqual(name, "办公文件")
        self.assertTrue(os.path.isfile(dest))

    def test_config_extension_with_leading_dot_still_matches(self):
        cfg = self.make_config([
            {"name": "图片", "extensions": [".png"], "folder": "图片"},
        ])
        src = self.write_file(os.path.join(self.desktop, "pic.png"))
        name, dest = file_manager.categorize_file(src, cfg)
        self.assertEqual(name, "图片")
        self.assertTrue(os.path.isfile(dest))

    def test_creates_category_folder_when_missing(self):
        cfg = self.make_config()
        folder = os.path.join(self.storage, "压缩包")
        self.assertFalse(os.path.isdir(folder))
        src = self.write_file(os.path.join(self.desktop, "pack.zip"))
        file_manager.categorize_file(src, cfg)
        self.assertTrue(os.path.isdir(folder))

    def test_name_conflict_renames_and_keeps_original(self):
        cfg = self.make_config()
        existing = self.write_file(os.path.join(self.storage, "办公文件", "a.doc"), "old")
        src = self.write_file(os.path.join(self.desktop, "a.doc"), "new")
        name, dest = file_manager.categorize_file(src, cfg)
        self.assertEqual(name, "办公文件")
        self.assertEqual(os.path.basename(dest), "a(1).doc")
        self.assertEqual(self.read_file(existing), "old")
        self.assertEqual(self.read_file(dest), "new")

    def test_returns_none_and_keeps_file_when_move_fails(self):
        cfg = self.make_config()
        src = self.write_file(os.path.join(self.desktop, "a.doc"), "keep")
        with mock.patch("file_manager.shutil.move", side_effect=OSError("boom")):
            result = file_manager.categorize_file(src, cfg)
        self.assertEqual(result, (None, None))
        self.assertTrue(os.path.exists(src), "移动失败时源文件必须保留")

    def test_other_desktop_files_untouched(self):
        cfg = self.make_config()
        keep = self.write_file(os.path.join(self.desktop, "keep.txt"))
        src = self.write_file(os.path.join(self.desktop, "go.doc"))
        file_manager.categorize_file(src, cfg)
        self.assertTrue(os.path.exists(keep))


# ── move_into_category ───────────────────────────────────

class TestMoveIntoCategory(TempDirsMixin, unittest.TestCase):

    def setUp(self):
        super().setUp()
        self.cfg = self.make_config()
        self.pics = CATEGORIES[2]  # 图片

    def test_moves_file_into_category(self):
        src = self.write_file(os.path.join(self.desktop, "a.png"))
        name, dest = file_manager.move_into_category(self.cfg, self.pics, src)
        self.assertEqual(name, "a.png")
        self.assertTrue(os.path.isfile(dest))
        self.assertFalse(os.path.exists(src))
        self.assertEqual(os.path.dirname(dest), os.path.join(self.storage, "图片"))
        self.assertInsideTmp(dest)

    def test_returns_none_for_nonexistent_source(self):
        ghost = os.path.join(self.desktop, "ghost.png")
        self.assertEqual(
            file_manager.move_into_category(self.cfg, self.pics, ghost), (None, None)
        )

    def test_rejects_category_folder_itself(self):
        folder = os.path.join(self.storage, "图片")
        os.makedirs(folder, exist_ok=True)
        self.assertEqual(
            file_manager.move_into_category(self.cfg, self.pics, folder), (None, None)
        )
        self.assertTrue(os.path.isdir(folder), "分类文件夹本身必须原地不动")

    def test_rejects_storage_root(self):
        self.assertEqual(
            file_manager.move_into_category(self.cfg, self.pics, self.storage),
            (None, None),
        )
        self.assertTrue(os.path.isdir(self.storage))

    def test_skips_entry_already_inside_target(self):
        inner = self.write_file(os.path.join(self.storage, "图片", "inner.png"))
        self.assertEqual(
            file_manager.move_into_category(self.cfg, self.pics, inner), (None, None)
        )
        self.assertTrue(os.path.exists(inner))

    def test_moves_directory_into_category(self):
        src_dir = os.path.join(self.desktop, "myfolder")
        self.write_file(os.path.join(src_dir, "inside.txt"))
        name, dest = file_manager.move_into_category(self.cfg, self.pics, src_dir)
        self.assertEqual(name, "myfolder")
        self.assertTrue(os.path.isdir(dest))
        self.assertTrue(os.path.isfile(os.path.join(dest, "inside.txt")))
        self.assertFalse(os.path.exists(src_dir))

    def test_name_conflict_renames_on_move(self):
        existing = self.write_file(os.path.join(self.storage, "图片", "a.png"), "old")
        src = self.write_file(os.path.join(self.desktop, "a.png"), "new")
        name, dest = file_manager.move_into_category(self.cfg, self.pics, src)
        self.assertEqual(name, "a(1).png")
        self.assertEqual(os.path.basename(dest), "a(1).png")
        self.assertEqual(self.read_file(existing), "old", "已存在的同名文件不得被覆盖")
        self.assertEqual(self.read_file(dest), "new")

    def test_returns_none_and_keeps_source_when_move_fails(self):
        src = self.write_file(os.path.join(self.desktop, "a.png"), "keep")
        with mock.patch("file_manager.shutil.move", side_effect=OSError("boom")):
            result = file_manager.move_into_category(self.cfg, self.pics, src)
        self.assertEqual(result, (None, None))
        self.assertTrue(os.path.exists(src), "移动失败时源文件必须保留")

    def test_creates_category_folder_when_missing(self):
        folder = os.path.join(self.storage, "图片")
        self.assertFalse(os.path.isdir(folder))
        src = self.write_file(os.path.join(self.desktop, "a.png"))
        file_manager.move_into_category(self.cfg, self.pics, src)
        self.assertTrue(os.path.isdir(folder))


# ── did_move：调用方判定（失败不能被当成功）──────────────
#
# AW-18：`move_into_category` / `categorize_file` 失败时返回 (None, None)，
# 而**非空元组恒为真**——旧 GUI 代码写 `if move_into_category(...)` 会把失败
# 当成功（UI 显示已收纳、实际没动）。判定逻辑抽成纯函数 did_move 以便单测。

class TestDidMove(unittest.TestCase):
    """did_move 的纯逻辑：判的是返回值里的 dest，不是元组本身。"""

    def test_failure_tuple_is_not_a_move(self):
        self.assertFalse(file_manager.did_move((None, None)))

    def test_success_tuple_is_a_move(self):
        self.assertTrue(
            file_manager.did_move(("图片", os.path.join("x", "a.png")))
        )

    def test_judgement_only_depends_on_dest(self):
        # 只看 dest 是否为 None，不依赖 name 的真假
        self.assertTrue(file_manager.did_move((None, os.path.join("x", "a.png"))))

    def test_none_result_is_not_a_move(self):
        self.assertFalse(file_manager.did_move(None))

    def test_nonempty_tuple_is_truthy_the_root_of_the_bug(self):
        # 钉住陷阱本身：非空元组恒为真，正是旧写法必然误判的原因。
        self.assertTrue(bool((None, None)))


class TestCallersCountMovesCorrectly(TempDirsMixin, unittest.TestCase):
    """端到端：让真实移动失败，断言调用方（用 did_move）不把它算作成功。"""

    def setUp(self):
        super().setUp()
        self.cfg = self.make_config()
        self.pics = CATEGORIES[2]  # 图片

    def _count_moved(self, src, result):
        """复刻 GUI 拖拽调用方的计数写法。"""
        moved = 0
        if src and file_manager.did_move(result):
            moved += 1
        return moved

    def test_failed_move_into_category_not_counted(self):
        src = self.write_file(os.path.join(self.desktop, "a.png"), "keep")
        with mock.patch("file_manager.shutil.move", side_effect=OSError("boom")):
            result = file_manager.move_into_category(self.cfg, self.pics, src)
        self.assertEqual(self._count_moved(src, result), 0, "移动失败不能被算作成功")
        self.assertTrue(os.path.exists(src), "失败时源文件必须保留")

    def test_successful_move_into_category_counted(self):
        src = self.write_file(os.path.join(self.desktop, "b.png"), "hi")
        result = file_manager.move_into_category(self.cfg, self.pics, src)
        self.assertEqual(self._count_moved(src, result), 1)

    def test_failed_categorize_not_counted(self):
        src = self.write_file(os.path.join(self.desktop, "c.png"), "keep")
        with mock.patch("file_manager.shutil.move", side_effect=OSError("boom")):
            result = file_manager.categorize_file(src, self.cfg)
        self.assertEqual(self._count_moved(src, result), 0, "移动失败不能被算作成功")
        self.assertTrue(os.path.exists(src), "失败时源文件必须保留")


if __name__ == "__main__":
    unittest.main()
