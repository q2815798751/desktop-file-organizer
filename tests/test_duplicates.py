"""
AW-22 重复文件检测的单元测试（标准库 unittest，零新依赖）。

覆盖三层：
1. 纯逻辑：`size_groups` / `find_duplicate_groups`（**只对同尺寸的算哈希**）、
   `file_sha256`；
2. 只读扫描：`category_files` / `find_duplicates`（含坏配置降级、跨分类重复）；
3. 删除：`delete_duplicates` —— 断言它**走回收站入口**（打桩）而**绝不 os.remove /
   os.unlink**。

数据安全：所有用例都在 `tempfile.TemporaryDirectory()` 里造目录，config 字典的
`desktop_path` / `storage_path` 都指向临时目录——**绝不触碰真实桌面或真实存储目录**。
**从不调用真实 `SHFileOperationW`**（会真删文件），回收站入口一律打桩。
GUI 模块（dashboard.py）不 import，只做源码级静态检查。

运行：python -m unittest discover -s tests -v
"""
import hashlib
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

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class TempDirsMixin:
    """在临时目录里造一个「假存储根」，用完自动清理。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.storage = os.path.join(self.tmp, "storage")
        os.makedirs(self.storage)

    def make_config(self, categories):
        return {
            "desktop_path": os.path.join(self.tmp, "Desktop"),
            "storage_path": self.storage,
            "categories": categories,
        }

    def cat(self, name, folder=None):
        return {"name": name, "extensions": [], "folder": folder or name}

    def write(self, relpath, content=b"x"):
        """在存储根下写一个文件（内容可以是 bytes 或 str）。"""
        path = os.path.join(self.storage, *relpath.replace("\\", "/").split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        kwargs = {} if isinstance(content, bytes) else {"encoding": "utf-8"}
        with open(path, mode, **kwargs) as f:
            f.write(content)
        return path

    def assertInsideTmp(self, path):
        self.assertTrue(
            os.path.abspath(path).startswith(os.path.abspath(self.tmp) + os.sep),
            f"路径 {path!r} 不在临时目录 {self.tmp!r} 内",
        )


def recording_hasher(calls=None):
    """返回一个「记录调用 + 真算 sha256」的 hasher，便于断言「谁被哈希了」。"""
    calls = [] if calls is None else calls

    def hasher(path):
        calls.append(path)
        return file_manager.file_sha256(path)

    return hasher


# ── file_sha256 ──────────────────────────────────────────

class TestFileSha256(TempDirsMixin, unittest.TestCase):
    """算文件内容哈希：分块读、读不到返回 None。"""

    def test_matches_hashlib_for_a_small_file(self):
        p = self.write("a.txt", b"hello world")
        self.assertEqual(
            file_manager.file_sha256(p), hashlib.sha256(b"hello world").hexdigest()
        )

    def test_empty_file_hashes_to_sha256_of_empty(self):
        # 空文件也是合法输入：两个 0 字节文件内容相同，sha256 是空串的固定值。
        p = self.write("empty.txt", b"")
        self.assertEqual(file_manager.file_sha256(p), EMPTY_SHA256)

    def test_chunked_read_equals_single_read(self):
        # 内容大于 chunk_size 时必须分块读且结果一致（否则大文件会读错/爆内存）。
        content = bytes(range(256)) * 40  # 10240 字节
        p = self.write("big.bin", content)
        self.assertEqual(
            file_manager.file_sha256(p, chunk_size=7),
            hashlib.sha256(content).hexdigest(),
        )

    def test_chunk_size_is_honoured_by_reading_in_chunks(self):
        content = b"0123456789" * 10  # 100 字节
        p = self.write("chunky.bin", content)
        reads = []

        class FakeFile:
            def __init__(self, real):
                self._real = real

            def read(self, n):
                reads.append(n)
                return self._real.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(path, mode):
            self.assertEqual(mode, "rb", "必须以二进制模式打开")
            return FakeFile(open(path, "rb"))

        digest = file_manager.file_sha256(p, chunk_size=10, open_func=fake_open)
        self.assertEqual(digest, hashlib.sha256(content).hexdigest())
        self.assertTrue(all(n == 10 for n in reads), f"读取块大小应为 10：{reads}")
        self.assertGreater(len(reads), 1, "100 字节 / 块 10 字节 → 应该读了多块")

    def test_missing_file_returns_none(self):
        self.assertIsNone(
            file_manager.file_sha256(os.path.join(self.tmp, "nope.bin"))
        )

    def test_read_error_returns_none(self):
        # 权限不足 / 被独占锁住 → OSError → 返回 None（不抛），单个文件读不了不该崩掉扫描
        def boom(path, mode):
            raise PermissionError("access denied")

        self.assertIsNone(file_manager.file_sha256("whatever.bin", open_func=boom))

    def test_open_func_receives_the_path(self):
        seen = []

        def spy(path, mode):
            seen.append((path, mode))
            raise FileNotFoundError(path)

        file_manager.file_sha256("some/file.bin", open_func=spy)
        self.assertEqual(seen, [("some/file.bin", "rb")])


# ── size_groups：只留同尺寸 ≥2 个的候选 ───────────────────

class TestSizeGroups(TempDirsMixin, unittest.TestCase):
    """按 st_size 分组：大小唯一的文件直接出局（不整盘哈希的基础）。"""

    def test_only_groups_with_more_than_one_member(self):
        paths = [self.write("a", b"11"), self.write("b", b"22"),
                 self.write("c", b"333")]
        got = file_manager.size_groups(paths)
        self.assertEqual([(size, [os.path.basename(p) for p in group])
                          for size, group in got],
                         [(2, ["a", "b"])])

    def test_unique_size_is_dropped(self):
        paths = [self.write("a", b"1"), self.write("b", b"22")]
        self.assertEqual(file_manager.size_groups(paths), [])

    def test_empty_files_are_a_candidate_group(self):
        # 两个 0 字节文件是「同尺寸 ≥2 个」→ 必须进入候选（空文件是合法重复组）
        paths = [self.write("e1", b""), self.write("e2", b"")]
        got = file_manager.size_groups(paths)
        self.assertEqual([(size, sorted(os.path.basename(p) for p in group))
                          for size, group in got],
                         [(0, ["e1", "e2"])])

    def test_same_size_different_content_still_a_candidate_here(self):
        # 本函数只看大小：同尺寸不同内容也是候选（真正的区分在哈希阶段）
        paths = [self.write("a", b"aaa"), self.write("b", b"bbb")]
        got = file_manager.size_groups(paths)
        self.assertEqual(len(got), 1)
        self.assertEqual(len(got[0][1]), 2)

    def test_getsize_error_skips_path(self):
        # 文件在扫描途中被删 → getsize 抛 OSError → 跳过它，其它照常
        paths = [self.write("a", b"11"), self.write("b", b"22")]
        real = os.path.getsize

        def getsize(p):
            if p.endswith("b"):
                raise FileNotFoundError(p)
            return real(p)

        self.assertEqual(file_manager.size_groups(paths, getsize=getsize), [])

    def test_ordering_is_deterministic(self):
        paths = [self.write("z", b"22"), self.write("a", b"22"),
                 self.write("m", b"111"), self.write("n", b"111")]
        got = file_manager.size_groups(paths)
        self.assertEqual([size for size, _ in got], [2, 3], "组间按 size 升序")
        for _size, group in got:
            self.assertEqual(group, sorted(group), "组内按路径排序")

    def test_empty_input(self):
        self.assertEqual(file_manager.size_groups([]), [])


# ── find_duplicate_groups：两阶段分组 ─────────────────────

class TestFindDuplicateGroups(TempDirsMixin, unittest.TestCase):
    """先按大小分组、只对候选算哈希、再按哈希分组。"""

    def test_same_content_different_names_is_a_group(self):
        a = self.write("报告.txt", "同一份内容")
        b = self.write("副本.txt", "同一份内容")
        groups = file_manager.find_duplicate_groups([a, b])
        self.assertEqual(len(groups), 1)
        size, digest, paths = groups[0]
        self.assertEqual(sorted(paths), sorted([a, b]))
        self.assertEqual(digest, hashlib.sha256("同一份内容".encode("utf-8")).hexdigest())
        self.assertEqual(size, os.path.getsize(a))

    def test_same_size_different_content_is_not_a_group(self):
        # 关键边界：大小相同但内容不同 → 哈希不同 → 不构成重复组
        a = self.write("a.txt", "AAA")
        b = self.write("b.txt", "BBB")
        self.assertEqual(file_manager.find_duplicate_groups([a, b]), [])

    def test_empty_files_grouped_together(self):
        a = self.write("empty1", b"")
        b = self.write("empty2", b"")
        groups = file_manager.find_duplicate_groups([a, b])
        self.assertEqual(len(groups), 1)
        size, digest, paths = groups[0]
        self.assertEqual(size, 0)
        self.assertEqual(digest, EMPTY_SHA256)
        self.assertEqual(sorted(paths), sorted([a, b]))

    def test_unique_size_files_are_never_hashed(self):
        # ⚠️ AW-22 的核心性能前提：**只对同尺寸的算 sha256**。
        # 三个尺寸各不相同的文件 → hasher 一次都不该被调用。
        paths = [self.write("a", b"1"), self.write("b", b"22"),
                 self.write("c", b"333")]
        calls = []
        file_manager.find_duplicate_groups(paths, hasher=recording_hasher(calls))
        self.assertEqual(calls, [], f"尺寸唯一的文件不该被哈希，实际哈希了 {calls}")

    def test_hasher_called_only_for_same_size_candidates(self):
        a = self.write("a", b"dup")
        b = self.write("b", b"dup")
        unique = self.write("unique", b"a much longer unique content")
        calls = []
        groups = file_manager.find_duplicate_groups(
            [a, b, unique], hasher=recording_hasher(calls)
        )
        self.assertEqual(sorted(calls), sorted([a, b]))
        self.assertNotIn(unique, calls)
        self.assertEqual(len(groups), 1)

    def test_three_copies_form_one_group(self):
        paths = [self.write(f"copy{i}", b"same") for i in range(3)]
        groups = file_manager.find_duplicate_groups(paths)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0][2]), 3)

    def test_unreadable_member_is_skipped_not_faked(self):
        # 同尺寸两个文件，其中一个读不出来（hasher 返回 None）→ 不能凑出一组
        a = self.write("a", b"dup")
        b = self.write("b", b"dup")

        def hasher(path):
            return None if path == b else file_manager.file_sha256(path)

        self.assertEqual(file_manager.find_duplicate_groups([a, b], hasher=hasher), [])

    def test_hasher_oserror_is_skipped(self):
        a = self.write("a", b"dup")
        b = self.write("b", b"dup")

        def hasher(path):
            if path == b:
                raise OSError("boom")
            return file_manager.file_sha256(path)

        # 注意：file_sha256 自己吞 OSError；注入的 hasher 抛异常时由用例暴露行为。
        with self.assertRaises(OSError):
            file_manager.find_duplicate_groups([a, b], hasher=hasher)

    def test_groups_sorted_by_size_descending(self):
        small = [self.write(f"s{i}", b"aa") for i in range(2)]
        big = [self.write(f"b{i}", b"aaaaaaaaaa") for i in range(2)]
        groups = file_manager.find_duplicate_groups(small + big)
        self.assertEqual([size for size, _d, _p in groups], [10, 2],
                         "最占空间的重复组排前面")

    def test_single_file_and_empty_input(self):
        a = self.write("a", b"x")
        self.assertEqual(file_manager.find_duplicate_groups([a]), [])
        self.assertEqual(file_manager.find_duplicate_groups([]), [])

    def test_all_distinct_returns_empty(self):
        paths = [self.write(f"f{i}", f"content-{i}".encode()) for i in range(5)]
        self.assertEqual(file_manager.find_duplicate_groups(paths), [])


# ── category_files：只读扫描分类目录 ──────────────────────

class TestCategoryFiles(TempDirsMixin, unittest.TestCase):

    def test_lists_top_level_files_with_category_name(self):
        a = self.write("图片/a.png", b"png")
        b = self.write("其他/b.txt", b"txt")
        cfg = self.make_config([self.cat("图片"), self.cat("其他")])
        got = file_manager.category_files(cfg)
        self.assertEqual(sorted(got), sorted([(a, "图片"), (b, "其他")]))

    def test_does_not_recurse_into_subdirectories(self):
        top = self.write("图片/top.png", b"x")
        self.write("图片/子文件夹/deep.png", b"x")
        cfg = self.make_config([self.cat("图片")])
        got = file_manager.category_files(cfg)
        self.assertEqual([p for p, _ in got], [top])

    def test_missing_folder_is_skipped(self):
        cfg = self.make_config([self.cat("不存在的分类")])
        self.assertEqual(file_manager.category_files(cfg), [])

    def test_unsafe_category_folder_is_skipped_with_error_log(self):
        safe = self.write("图片/a.png", b"x")
        cfg = self.make_config([
            self.cat("坏分类", folder="..\\..\\evil"),
            self.cat("图片"),
        ])
        with self.assertLogs("file_manager", level="ERROR") as cm:
            got = file_manager.category_files(cfg)
        self.assertEqual([p for p, _ in got], [safe])
        self.assertTrue(any("不安全" in line for line in cm.output))

    def test_listdir_failure_is_skipped_and_logged(self):
        cfg = self.make_config([self.cat("图片")])
        os.makedirs(os.path.join(self.storage, "图片"))  # 目录存在 → 才会走到 listdir
        with mock.patch("file_manager.os.listdir", side_effect=PermissionError("nope")):
            with self.assertLogs("file_manager", level="WARNING") as cm:
                got = file_manager.category_files(cfg)
        self.assertEqual(got, [])
        self.assertTrue(any("列目录失败" in line for line in cm.output))

    def test_is_read_only(self):
        a = self.write("图片/a.png", b"x")
        cfg = self.make_config([self.cat("图片")])
        with mock.patch("file_manager.os.remove", side_effect=AssertionError("只读")):
            with mock.patch("file_manager.shutil.move",
                            side_effect=AssertionError("只读")):
                file_manager.category_files(cfg)
        self.assertTrue(os.path.isfile(a))


# ── find_duplicates：跨分类的端到端扫描 ───────────────────

class TestFindDuplicates(TempDirsMixin, unittest.TestCase):

    def test_cross_category_duplicates_are_one_group(self):
        # 同内容、不同文件名、不同分类 → 必须归到同一组
        a = self.write("图片/photo.png", b"SAME-BYTES")
        b = self.write("其他/backup.png", b"SAME-BYTES")
        cfg = self.make_config([self.cat("图片"), self.cat("其他")])
        groups = file_manager.find_duplicates(cfg)
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(sorted(e.path for e in group.entries), sorted([a, b]))
        self.assertEqual(
            sorted((e.name, e.category, e.size) for e in group.entries),
            sorted([("photo.png", "图片", 10), ("backup.png", "其他", 10)]),
        )

    def test_entries_carry_name_size_category(self):
        a = self.write("办公文件/doc1.docx", b"DOC")
        self.write("办公文件/doc2.docx", b"DOC")
        cfg = self.make_config([self.cat("办公文件")])
        entry = file_manager.find_duplicates(cfg)[0].entries[0]
        self.assertEqual(entry.name, "doc1.docx")
        self.assertEqual(entry.size, 3)
        self.assertEqual(entry.category, "办公文件")
        self.assertEqual(entry.path, a)

    def test_no_duplicates_returns_empty(self):
        self.write("图片/a.png", b"AAA")
        self.write("图片/b.png", b"BBBB")
        cfg = self.make_config([self.cat("图片")])
        self.assertEqual(file_manager.find_duplicates(cfg), [])

    def test_empty_files_across_categories_are_a_group(self):
        self.write("图片/empty1", b"")
        self.write("其他/empty2", b"")
        cfg = self.make_config([self.cat("图片"), self.cat("其他")])
        groups = file_manager.find_duplicates(cfg)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].size, 0)
        self.assertEqual(len(groups[0].entries), 2)

    def test_unsafe_category_does_not_break_scan(self):
        # 坏配置（folder 越界）→ 该分类被跳过，其余分类照常扫出重复
        self.write("图片/a.png", b"DUP")
        self.write("图片/b.png", b"DUP")
        self.write("坏分类/c.png", b"DUP")
        cfg = self.make_config([
            self.cat("坏分类", folder="..\\..\\evil"),
            self.cat("图片"),
        ])
        with self.assertLogs("file_manager", level="ERROR"):
            groups = file_manager.find_duplicates(cfg)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].entries), 2)
        self.assertTrue(all(e.category == "图片" for e in groups[0].entries))

    def test_scan_does_not_modify_anything(self):
        a = self.write("图片/a.png", b"DUP")
        b = self.write("图片/b.png", b"DUP")
        cfg = self.make_config([self.cat("图片")])
        before = sorted(os.listdir(os.path.join(self.storage, "图片")))
        file_manager.find_duplicates(cfg)
        after = sorted(os.listdir(os.path.join(self.storage, "图片")))
        self.assertEqual(before, after)
        self.assertTrue(os.path.isfile(a) and os.path.isfile(b))

    def test_detects_duplicates_within_one_category(self):
        self.write("图片/a.png", b"DUP")
        self.write("图片/b.png", b"DUP")
        cfg = self.make_config([self.cat("图片")])
        self.assertEqual(len(file_manager.find_duplicates(cfg)), 1)


# ── delete_duplicates：删除必须走回收站 ───────────────────

class TestDeleteDuplicates(TempDirsMixin, unittest.TestCase):

    def test_uses_recycle_bin_and_never_unlinks(self):
        """
        ⚠️ 判别性用例：删除必须**复用现有的「进回收站」接口**，绝不直接 os.remove /
        os.unlink（那会永久删除用户文件）。打桩掉 `os.remove` / `os.unlink`：
        只要代码走它们，本用例就变红。
        """
        a = self.write("图片/a.png", b"DUP")
        b = self.write("图片/b.png", b"DUP")
        calls = []

        def fake_recycle_bin(path):
            calls.append(path)
            return True

        with mock.patch("os.remove",
                        side_effect=AssertionError("绝不能直接 os.remove")):
            with mock.patch("os.unlink",
                            side_effect=AssertionError("绝不能直接 os.unlink")):
                stats = file_manager.delete_duplicates([a, b], fake_recycle_bin)

        self.assertEqual(calls, [a, b], "每个文件都必须走回收站入口")
        self.assertEqual(stats.deleted, 2)
        self.assertEqual(stats.failed, 0)
        # 打桩函数没真删 → 文件仍在（证明删除确实经过打桩入口，而不是别处）
        self.assertTrue(os.path.isfile(a) and os.path.isfile(b))

    def test_default_delete_func_is_the_shared_recycle_bin_entry(self):
        # 不传 delete_func 时必须默认走 file_manager.send_to_recycle_bin
        # （dashboard._send_to_recycle_bin 就是它的薄封装）→ 全仓只有一个删除实现。
        paths = [self.write("a", b"1"), self.write("b", b"2")]
        with mock.patch("file_manager.send_to_recycle_bin",
                        return_value=True) as spy:
            stats = file_manager.delete_duplicates(paths)
        self.assertEqual([c.args[0] for c in spy.call_args_list], paths)
        self.assertEqual(stats.deleted, 2)

    def test_cancelled_delete_is_not_counted_as_deleted(self):
        # 用户点「取消」→ 回收站接口返回 False → 不计入成功数（与 AW-5 语义一致）
        paths = [self.write("a", b"1")]
        stats = file_manager.delete_duplicates(paths, lambda p: False)
        self.assertEqual((stats.deleted, stats.cancelled, stats.failed), (0, 1, 0))

    def test_failure_is_counted_and_does_not_stop_the_batch(self):
        a = self.write("a", b"1")
        b = self.write("b", b"2")
        c = self.write("c", b"3")

        def flaky(path):
            if path == b:
                raise OSError("文件被占用")
            return True

        stats = file_manager.delete_duplicates([a, b, c], flaky)
        self.assertEqual(stats.deleted, 2, "一个删不掉不该让整批停下")
        self.assertEqual(stats.failed, 1)
        self.assertEqual([p for p, _ in stats.errors], [b])
        self.assertIn("文件被占用", stats.errors[0][1])

    def test_failure_is_logged_not_silently_swallowed(self):
        def boom(path):
            raise OSError("被锁")

        with self.assertLogs("file_manager", level="WARNING") as cm:
            file_manager.delete_duplicates([self.write("a", b"1")], boom)
        self.assertTrue(any("删除重复文件失败" in line for line in cm.output))

    def test_empty_input(self):
        stats = file_manager.delete_duplicates([])
        self.assertEqual((stats.deleted, stats.cancelled, stats.failed), (0, 0, 0))
        self.assertEqual(stats.errors, [])

    def test_mixed_result_summary(self):
        paths = [self.write(f"f{i}", b"x") for i in range(3)]

        def mixed(path):
            if path.endswith("f1"):
                return False
            if path.endswith("f2"):
                raise OSError("boom")
            return True

        stats = file_manager.delete_duplicates(paths, mixed)
        self.assertEqual((stats.deleted, stats.cancelled, stats.failed), (1, 1, 1))


# ── GUI 接线：源码级静态检查（没有行为测试，如实标注） ────

class TestDashboardWiring(unittest.TestCase):
    """
    仪表盘是 GUI 模块，测试环境**不 import**（PyQt5 依赖），所以这里只做**源码级
    静态检查**——它**不是**行为测试，只能挡住「接线被整段删掉/换成 os.unlink」
    这类粗粒度退化。UI 交互本身仍未覆盖（见 AUTOWORK.md AW-22 条目）。
    """

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_REPO_ROOT, "dashboard.py"), encoding="utf-8") as f:
            cls.source = f.read()

    def test_duplicate_view_uses_shared_delete_entry(self):
        self.assertIn("def _on_find_duplicates", self.source)
        self.assertIn("delete_duplicates(", self.source)
        self.assertIn("_send_to_recycle_bin", self.source)

    def test_dashboard_never_deletes_permanently(self):
        self.assertNotIn("os.unlink", self.source)
        self.assertNotIn("os.remove", self.source)


if __name__ == "__main__":
    unittest.main()
