"""
file_manager.py 纯逻辑单元测试（标准库 unittest，零新依赖）。

数据安全：所有涉及移动/删除/重命名的用例都在 tempfile.TemporaryDirectory()
里造目录，并通过 config 字典（以及 unittest.mock.patch）把 desktop_path /
storage_path 指向临时目录——**绝不触碰真实桌面或真实用户目录**。
GUI 模块（dashboard.py / desktop_panel.py）不导入。

运行：python -m unittest discover -s tests -v
"""
import os
import subprocess
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


# ── AW-19：坏配置必须「可见地降级」，绝不崩 ──────────────

class TestUnsafeCategoryDegradation(TempDirsMixin, unittest.TestCase):
    """
    AW-3 引入的回归：`UnsafeCategoryFolder` 全仓无人捕获，导致
    init_folders / categorize_file / get_files_in_category / move_into_category
    四条链遇到非法 `folder` 全部原样抛出（启动即崩 / abort 事件循环 / GUI 崩）。
    现在各入口都改成「捕获 → 记 ERROR 日志 → 跳过该分类」。
    """

    def _bad_cat(self, folder="..\\..\\evil", name="恶意分类"):
        return {"name": name, "extensions": ["evil"], "folder": folder}

    def _cfg_with(self, *cats):
        return self.make_config(categories=[dict(c) for c in cats])

    # —— 3. 非字符串 folder 统一成 UnsafeCategoryFolder（不再是 TypeError）——

    def test_non_string_folder_is_rejected_by_pure_validator(self):
        err = file_manager.category_folder_error(self.storage, 123)
        self.assertIsNotNone(err, "非字符串 folder 应被判为不安全")

    def test_non_string_folder_raises_unsafe_not_typeerror(self):
        cfg = self.make_config()
        cat = {"name": "x", "extensions": [], "folder": 123}
        with self.assertRaises(file_manager.UnsafeCategoryFolder):
            file_manager.get_category_folder(cfg, cat)

    # —— safe_category_folder：好分类照常解析 ——

    def test_safe_folder_returns_path_for_good_category(self):
        cfg = self.make_config()
        cat = {"name": "图片", "extensions": [], "folder": "pics"}
        self.assertEqual(
            file_manager.safe_category_folder(cfg, cat),
            os.path.join(self.storage, "pics"),
        )

    # —— safe_category_folder：坏分类 → None + 可见的 ERROR 记录 ——

    def test_safe_folder_skips_bad_category_and_logs(self):
        cfg = self.make_config()
        with self.assertLogs("file_manager", level="ERROR") as cm:
            got = file_manager.safe_category_folder(cfg, self._bad_cat())
        self.assertIsNone(got)
        joined = "\n".join(cm.output)
        self.assertIn("已跳过", joined)
        self.assertIn("恶意分类", joined)

    def test_unsafe_category_message_is_pure_and_mentions_skip(self):
        msg = file_manager.unsafe_category_message({"name": "办公文件"}, "越界")
        self.assertIn("办公文件", msg)
        self.assertIn("已跳过", msg)
        self.assertIn("越界", msg)

    # —— get_files_in_category 降级（GUI 刷新链）——

    def test_get_files_in_category_skips_bad_category(self):
        cfg = self.make_config()
        with self.assertLogs("file_manager", level="ERROR") as cm:
            got = file_manager.get_files_in_category(cfg, self._bad_cat())
        self.assertEqual(got, [])
        self.assertIn("已跳过", "\n".join(cm.output))

    # —— categorize_file 降级（file_watcher 的 QTimer 槽）——

    def test_categorize_file_does_not_raise_on_bad_category(self):
        cfg = self._cfg_with(self._bad_cat())
        src = self.write_file(os.path.join(self.desktop, "a.evil"), "data")
        with self.assertLogs("file_manager", level="ERROR"):
            name, dest = file_manager.categorize_file(src, cfg)  # 不抛异常
        self.assertEqual((name, dest), (None, None))
        self.assertTrue(os.path.exists(src), "源文件必须留在原处")

    def test_categorize_file_skips_bad_and_uses_next_safe_category(self):
        bad = self._bad_cat()
        good = {"name": "好分类", "extensions": ["evil"], "folder": "good"}
        cfg = self._cfg_with(bad, good)
        src = self.write_file(os.path.join(self.desktop, "a.evil"), "data")
        with self.assertLogs("file_manager", level="ERROR"):
            name, dest = file_manager.categorize_file(src, cfg)
        self.assertEqual(name, "好分类", "坏分类应被跳过、由下一个安全分类接管")
        moved = os.path.join(self.storage, "good", "a.evil")
        self.assertTrue(os.path.isfile(moved))
        self.assertInsideTmp(moved)

    # —— move_into_category 降级（拖拽链）——

    def test_move_into_category_skips_bad_category(self):
        cfg = self._cfg_with(self._bad_cat())
        src = self.write_file(os.path.join(self.desktop, "a.txt"), "data")
        with self.assertLogs("file_manager", level="ERROR"):
            result = file_manager.move_into_category(cfg, self._bad_cat(), src)
        self.assertEqual(result, (None, None))
        self.assertTrue(os.path.exists(src), "拖拽到坏分类不得移动源文件")

    # —— junction / 符号链接逃逸：realpath 复检 ——

    def test_realpath_escape_detected_when_target_resolves_outside(self):
        # 模拟「storage\\evil 已存在且是指向根外的 junction」：realpath 解析到根外
        root = self.storage
        outside = os.path.join(self.tmp, "outside")
        target = os.path.join(root, "evil")
        real = os.path.realpath

        def fake_realpath(p):
            if os.path.normcase(os.path.abspath(p)) == os.path.normcase(
                os.path.abspath(target)
            ):
                return outside
            return real(p)

        with mock.patch("file_manager.os.path.realpath", side_effect=fake_realpath):
            err = file_manager.realpath_escape_error(root, target)
        self.assertIsNotNone(err, "realpath 落到根外必须被判越界")

    def test_realpath_inside_is_allowed(self):
        # 正常（含尚不存在）的目标解析仍在根内 → 放行，不误伤新分类
        target = os.path.join(self.storage, "pics")
        self.assertIsNone(
            file_manager.realpath_escape_error(self.storage, target)
        )

    @unittest.skipUnless(os.name == "nt", "junction 只在 Windows 上可测")
    def test_real_junction_escape_is_rejected(self):
        """用真实 mklink /J 复现：词法校验放行，realpath 复检必须拒绝。"""
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        link = os.path.join(self.storage, "evil")
        try:
            rc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", link, outside],
                capture_output=True,
            ).returncode
        except OSError:
            self.skipTest("无法调用 cmd/mklink")
        if rc != 0 or not os.path.isdir(link):
            self.skipTest("本环境无法创建 junction（mklink 失败）")
        # 清理：删 junction 链接本身（不动目标），先于 TemporaryDirectory 清理
        self.addCleanup(lambda: os.rmdir(link) if os.path.isdir(link) else None)

        # 词法校验会放行（这正是逃逸能发生的原因）
        self.assertIsNone(file_manager.category_folder_error(self.storage, "evil"))

        cfg = self.make_config()
        cat = {"name": "evil", "extensions": [], "folder": "evil"}
        with self.assertRaises(file_manager.UnsafeCategoryFolder):
            file_manager.get_category_folder(cfg, cat)
        with self.assertLogs("file_manager", level="ERROR") as cm:
            self.assertIsNone(file_manager.safe_category_folder(cfg, cat))
        self.assertIn("已跳过", "\n".join(cm.output))


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


# ── AW-4：move_into_category 必须拒绝存储根及其所有祖先 ──

class TestMoveIntoCategoryRejectsStorageAncestors(TempDirsMixin, unittest.TestCase):
    """
    旧防护只拒绝「分类文件夹本身」和「存储根」这一层。把存储根的**父目录**
    （如 `Documents`）拖进面板，会把整个存储目录连同所有分类搬进某个分类 →
    存储根位移、配置全部失效。现在必须拒绝存储根**及其所有祖先**。

    存储根特意放深几层（tmp/base/sub/storage），以便测「多层祖先」，
    并确认 `startswith` 会误伤的前缀兄弟目录（`stor`）仍能正常收纳。
    """

    def setUp(self):
        super().setUp()
        self.nest = os.path.join(self.tmp, "base", "sub")
        os.makedirs(self.nest)
        self.storage = os.path.join(self.nest, "storage")
        os.makedirs(self.storage)
        self.cfg = self.make_config()
        self.pics = CATEGORIES[2]  # 图片

    def _assert_rejected(self, src):
        # ⚠️ 必须用 spy 证明「拒绝发生在搬移之前」：祖先目录本身包含目标分类，
        # 就算真的去搬也会因「移进自己的子目录」而失败——只看返回值 (None, None)
        # 区分不出「被防护挡住」和「搬移碰巧失败」。断言根本没调用搬移才是判别性的。
        with mock.patch("file_manager._move_no_clobber") as spy:
            result = file_manager.move_into_category(self.cfg, self.pics, src)
        self.assertEqual(result, (None, None))
        self.assertFalse(spy.called, "祖先目录必须在搬移之前就被拒绝，绝不能真的尝试移动")
        self.assertTrue(os.path.exists(src), "被拒绝的源必须原地不动")

    # —— 存储根本身 + 各级祖先，全部拒绝 ——

    def test_rejects_storage_root(self):
        self._assert_rejected(self.storage)

    def test_rejects_immediate_parent(self):
        # 存储根的父目录（相当于真实场景里的 Documents）
        self._assert_rejected(self.nest)

    def test_rejects_grandparent(self):
        self._assert_rejected(os.path.join(self.tmp, "base"))

    def test_rejects_top_ancestor(self):
        # 最高层祖先（相当于 ~ / 用户主目录）
        self._assert_rejected(self.tmp)

    def test_rejection_leaves_storage_and_categories_intact(self):
        # 拒绝后存储根与其下的分类目录必须一个没少（且根本没尝试搬移）
        cat_dir = os.path.join(self.storage, "图片")
        os.makedirs(cat_dir)
        self._assert_rejected(self.nest)
        self.assertTrue(os.path.isdir(self.storage))
        self.assertTrue(os.path.isdir(cat_dir))

    # —— 正常条目仍可移入（别把校验写得太狠）——

    def test_normal_desktop_file_still_moves(self):
        src = self.write_file(os.path.join(self.desktop, "a.png"))
        name, dest = file_manager.move_into_category(self.cfg, self.pics, src)
        self.assertEqual(name, "a.png")
        self.assertTrue(os.path.isfile(dest))
        self.assertFalse(os.path.exists(src))
        self.assertEqual(os.path.dirname(dest), os.path.join(self.storage, "图片"))
        self.assertInsideTmp(dest)

    def test_normal_desktop_directory_still_moves(self):
        src_dir = os.path.join(self.desktop, "myfolder")
        self.write_file(os.path.join(src_dir, "inside.txt"))
        name, dest = file_manager.move_into_category(self.cfg, self.pics, src_dir)
        self.assertEqual(name, "myfolder")
        self.assertTrue(os.path.isfile(os.path.join(dest, "inside.txt")))
        self.assertFalse(os.path.exists(src_dir))

    def test_prefix_sibling_directory_is_not_rejected(self):
        # `stor` 是存储根目录名 `storage` 的字符串前缀，但只是**兄弟目录**、并非祖先。
        # 用 startswith 判前缀的实现会把它误判成祖先而拒绝——这里必须能正常收纳。
        sibling = os.path.join(self.nest, "stor")
        self.write_file(os.path.join(sibling, "keep.txt"))
        name, dest = file_manager.move_into_category(self.cfg, self.pics, sibling)
        self.assertEqual(name, "stor")
        self.assertTrue(os.path.isfile(os.path.join(dest, "keep.txt")))
        self.assertFalse(os.path.exists(sibling))

    def test_deep_file_inside_storage_is_not_rejected_by_ancestor_rule(self):
        # 存储根**内部**的文件是后代、不是祖先：由「已在目标分类内」规则处理，
        # 别被本项误伤（放到另一个分类下仍可移动）。
        inner = self.write_file(os.path.join(self.storage, "图片", "inner.png"))
        # 目标就是它所在的分类 → 已在分类内，跳过（保持既有行为）
        self.assertEqual(
            file_manager.move_into_category(self.cfg, self.pics, inner), (None, None)
        )
        self.assertTrue(os.path.exists(inner))

    # —— 纯函数本身 ——

    def test_pure_function_rejects_ancestors(self):
        for src in (self.storage, self.nest, os.path.join(self.tmp, "base"), self.tmp):
            err = file_manager.storage_ancestor_error(self.storage, src)
            self.assertIsNotNone(err, f"{src!r} 是存储根的祖先/本身，应被拒绝")
            self.assertTrue(err.strip())

    def test_pure_function_allows_non_ancestors(self):
        for src in (
            os.path.join(self.desktop, "a.png"),
            os.path.join(self.nest, "stor"),          # 前缀兄弟目录
            os.path.join(self.tmp, "elsewhere"),
            os.path.join(self.storage, "图片", "x"),  # 存储根的后代
        ):
            self.assertIsNone(
                file_manager.storage_ancestor_error(self.storage, src),
                f"{src!r} 不是存储根的祖先，不该被拒绝",
            )

    def test_pure_function_allows_other_drive(self):
        # 不同盘符 → commonpath 抛 ValueError → 不可能是祖先 → 放行
        drive = os.path.splitdrive(self.storage)[0].upper()
        other = "Z:\\x" if drive != "Z:" else "Y:\\x"
        self.assertIsNone(file_manager.storage_ancestor_error(self.storage, other))


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


# ── AW-5：回收站删除的标志位与结果判定 ─────────────────────
#
# 旧 GUI 代码把 SHEmptyRecycleBin 的 SHERB_* 常量当成 FOF_* 用，漏掉了
# FOF_NOCONFIRMATION(0x10)（确认框照弹）；且从不检查 fAnyOperationsAborted，
# 用户点「取消」时 result==0 仍被当成删除成功。这两点被抽成纯函数以便单测——
# 测试**不调用**真实 SHFileOperation（那会真删文件）。

# 旧代码误用的 SHEmptyRecycleBin 标志（NOCONFIRMATION / NOPROGRESSUI / NOSOUND）
_SHERB_FLAGS_OLD = 0x0001 | 0x0002 | 0x0004


class TestBuildDeleteFlags(unittest.TestCase):
    """build_delete_flags 的纯逻辑：必须用正确的 FOF_* 组合。"""

    def test_all_four_required_flags_set(self):
        flags = file_manager.build_delete_flags()
        self.assertTrue(flags & 0x0040, "缺少 FOF_ALLOWUNDO(0x40)：会变成永久删除")
        self.assertTrue(flags & 0x0010, "缺少 FOF_NOCONFIRMATION(0x10)")
        self.assertTrue(flags & 0x0400, "缺少 FOF_NOERRORUI(0x400)")
        self.assertTrue(flags & 0x0004, "缺少 FOF_SILENT(0x4)")

    def test_noconfirmation_bit_is_present_the_regression(self):
        # 判别性：旧写法（SHERB_*）恰好没有 0x10，所以确认框照弹。
        self.assertTrue(file_manager.build_delete_flags() & 0x0010)
        self.assertFalse(_SHERB_FLAGS_OLD & 0x0010)

    def test_exact_value(self):
        # 0x40 | 0x10 | 0x400 | 0x4 == 0x454
        self.assertEqual(file_manager.build_delete_flags(), 0x0454)

    def test_is_not_the_old_shemptyrecyclebin_flags(self):
        self.assertNotEqual(file_manager.build_delete_flags(), _SHERB_FLAGS_OLD)


class TestInterpretDeleteResult(unittest.TestCase):
    """interpret_delete_result 的纯逻辑：只有 result==0 且未被取消才算成功。"""

    def test_success_is_true(self):
        self.assertTrue(file_manager.interpret_delete_result(0, False))

    def test_cancelled_is_not_success_the_regression(self):
        # 用户点「取消」：API 仍返回 0，但文件没删 → 绝不能算成功。
        self.assertFalse(file_manager.interpret_delete_result(0, True))

    def test_nonzero_result_is_failure(self):
        self.assertFalse(file_manager.interpret_delete_result(5, False))

    def test_nonzero_result_and_cancelled_is_failure(self):
        self.assertFalse(file_manager.interpret_delete_result(5, True))

    def test_aborted_accepts_ctypes_bool_int(self):
        # fAnyOperationsAborted 是 ctypes 的 BOOL（c_int）：0 为假、非 0 为真。
        self.assertTrue(file_manager.interpret_delete_result(0, 0))
        self.assertFalse(file_manager.interpret_delete_result(0, 1))
        self.assertFalse(file_manager.interpret_delete_result(0, 12345))


class TestDeleteResultCounting(unittest.TestCase):
    """复刻 dashboard._on_delete_files 的计数写法：被取消的不计入成功数。"""

    @staticmethod
    def _count_deleted(pairs):
        deleted = 0
        for result, aborted in pairs:
            if file_manager.interpret_delete_result(result, aborted):
                deleted += 1
        return deleted

    def test_cancelled_delete_not_counted(self):
        self.assertEqual(self._count_deleted([(0, True)]), 0)

    def test_only_real_deletes_counted(self):
        # 成功 + 取消 + 真失败 → 只算 1 个成功
        self.assertEqual(
            self._count_deleted([(0, False), (0, True), (1, False)]), 1
        )

    def test_all_success_counted(self):
        self.assertEqual(self._count_deleted([(0, False), (0, 0)]), 2)


# ── AW-7：文件稳定性判定 ──────────────────────────────────

class TestIsStable(unittest.TestCase):
    """is_stable 纯函数：注入 sizes 序列，断言稳定性判定规则。"""

    def test_two_equal_samples_is_stable(self):
        self.assertTrue(file_manager.is_stable([100, 100]))

    def test_zero_size_stable(self):
        # 空文件创建后一直为空 → 连续两次 0 → 稳定
        self.assertTrue(file_manager.is_stable([0, 0]))

    def test_growing_size_is_unstable(self):
        # 大文件正在复制：大小还在变 → 不稳定（本项要防的核心场景）
        self.assertFalse(file_manager.is_stable([100, 200]))

    def test_shrinking_size_is_unstable(self):
        self.assertFalse(file_manager.is_stable([200, 100]))

    def test_single_sample_is_unstable(self):
        # 只有一个样本 = 还没比过，不能冒险归类
        self.assertFalse(file_manager.is_stable([100]))

    def test_empty_is_unstable(self):
        self.assertFalse(file_manager.is_stable([]))

    def test_only_last_two_samples_decide(self):
        # 判定只看最后两个样本：早期变化不影响、最近一次仍在变则不稳定
        self.assertTrue(file_manager.is_stable([10, 20, 30, 30]))
        self.assertFalse(file_manager.is_stable([10, 10, 10, 20]))

    def test_min_samples_respected(self):
        self.assertFalse(file_manager.is_stable([5, 5], min_samples=3))
        self.assertTrue(file_manager.is_stable([5, 5, 5], min_samples=3))


class TestStableFilesIntegration(TempDirsMixin, unittest.TestCase):
    """stable_files 的真实文件系统行为（AW-7，临时文件）。"""

    def test_unchanged_file_is_stable(self):
        # 真实 os.path.getsize + 真实临时文件：不再改动 → 连续两次相同 → 稳定
        p = self.write_file(os.path.join(self.tmp, "a.txt"), "hello")
        stable, unstable = file_manager.stable_files([p], interval=0.0)
        self.assertEqual(stable, [p])
        self.assertEqual(unstable, [])

    def test_file_growing_between_samples_is_unstable(self):
        # 注入假 sleep，在「等待」期间向真实文件追加内容 → 复现「正在复制」
        p = self.write_file(os.path.join(self.tmp, "big.bin"), "x")

        def grow(_seconds):
            with open(p, "a", encoding="utf-8") as f:
                f.write("y" * 1000)

        stable, unstable = file_manager.stable_files([p], interval=1, sleep=grow)
        self.assertEqual(stable, [])
        self.assertEqual(unstable, [p])

    def test_missing_file_is_unstable(self):
        missing = os.path.join(self.tmp, "nope.txt")
        stable, unstable = file_manager.stable_files([missing], interval=0.0)
        self.assertEqual(stable, [])
        self.assertEqual(unstable, [missing])

    def test_file_removed_during_sampling_is_unstable(self):
        p = self.write_file(os.path.join(self.tmp, "gone.txt"), "x")

        def remove(_seconds):
            os.remove(p)

        stable, unstable = file_manager.stable_files([p], interval=1, sleep=remove)
        self.assertEqual(stable, [])
        self.assertEqual(unstable, [p])

    def test_batch_partitioned_by_growth(self):
        steady = self.write_file(os.path.join(self.tmp, "steady.txt"), "abc")
        growing = self.write_file(os.path.join(self.tmp, "growing.txt"), "a")

        def grow_one(_seconds):
            with open(growing, "a", encoding="utf-8") as f:
                f.write("b" * 100)

        stable, unstable = file_manager.stable_files(
            [steady, growing], interval=1, sleep=grow_one
        )
        self.assertEqual(stable, [steady])
        self.assertEqual(unstable, [growing])

    def test_batch_shares_single_wait(self):
        # 整批只 sleep 一次（不是逐文件 sleep）——否则 GUI 线程会卡 N × interval
        paths = [
            self.write_file(os.path.join(self.tmp, f"f{i}.txt"), "x")
            for i in range(3)
        ]
        calls = []

        def fake_sleep(seconds):
            calls.append(seconds)

        file_manager.stable_files(paths, interval=0.25, sleep=fake_sleep)
        self.assertEqual(calls, [0.25])

    def test_injected_getsize_sequence(self):
        # 注入 getsize 序列（单路径会被调用两次：采样前 / 采样后）
        growing = iter([10, 20])
        self.assertEqual(
            file_manager.stable_files(
                ["p"], getsize=lambda _p: next(growing), interval=0.0
            ),
            ([], ["p"]),
        )
        steady = iter([10, 10])
        self.assertEqual(
            file_manager.stable_files(
                ["p"], getsize=lambda _p: next(steady), interval=0.0
            ),
            (["p"], []),
        )

    def test_getsize_error_is_unstable(self):
        def boom(_p):
            raise OSError("boom")

        self.assertEqual(
            file_manager.stable_files(["p"], getsize=boom, interval=0.0),
            ([], ["p"]),
        )


class TestStabilityDecision(unittest.TestCase):
    """stability_decision 纯函数：重试策略。"""

    def test_stable_categorizes(self):
        self.assertEqual(
            file_manager.stability_decision(True, 0, 20),
            file_manager.ACTION_CATEGORIZE,
        )

    def test_stable_ignores_retries(self):
        self.assertEqual(
            file_manager.stability_decision(True, 999, 3),
            file_manager.ACTION_CATEGORIZE,
        )

    def test_unstable_retries(self):
        self.assertEqual(
            file_manager.stability_decision(False, 0, 20),
            file_manager.ACTION_RETRY,
        )

    def test_unstable_at_limit_gives_up(self):
        self.assertEqual(
            file_manager.stability_decision(False, 20, 20),
            file_manager.ACTION_GIVE_UP,
        )

    def test_unstable_beyond_limit_gives_up(self):
        self.assertEqual(
            file_manager.stability_decision(False, 21, 20),
            file_manager.ACTION_GIVE_UP,
        )

    def test_zero_max_retries_gives_up_immediately(self):
        self.assertEqual(
            file_manager.stability_decision(False, 0, 0),
            file_manager.ACTION_GIVE_UP,
        )


if __name__ == "__main__":
    unittest.main()
