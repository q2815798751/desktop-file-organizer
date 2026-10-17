"""
config.py 读写配置的单元测试（标准库 unittest，零新依赖）。

数据安全红线：CONFIG_PATH 在非打包状态下指向仓库根目录的 config.json。
本文件所有用例在 setUp 里 **先把 config.CONFIG_PATH 打桩到临时目录**，
保证绝不往仓库根目录写 config.json（跑完 git status 必须干净）。
所有文件操作都在 tempfile.TemporaryDirectory() 内，不导入 GUI 模块。

运行：python -m unittest discover -s tests -v
"""
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
import file_manager  # noqa: E402

# 与 config.DEFAULT_CONFIG 一致的精简分类表（仅测试用）
CATEGORIES = [
    {"name": "办公文件", "extensions": ["doc", "docx", "pdf"], "folder": "办公文件"},
    {"name": "压缩包", "extensions": ["zip", "rar"], "folder": "压缩包"},
    {"name": "图片", "extensions": ["png", "jpg"], "folder": "图片"},
]


class ConfigTestBase(unittest.TestCase):
    """把 CONFIG_PATH 打桩到临时目录，绝不动仓库根目录的 config.json。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.config_path = os.path.join(self.tmp, "config.json")

        patcher = mock.patch("config.CONFIG_PATH", self.config_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_raw(self, text):
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(text)

    def read_raw(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            return f.read()

    def corrupt_backups(self):
        """返回 CONFIG_PATH 旁的 .corrupt-<时间戳> 备份文件列表。"""
        d = os.path.dirname(self.config_path)
        prefix = os.path.basename(self.config_path) + ".corrupt-"
        return [
            os.path.join(d, n) for n in os.listdir(d) if n.startswith(prefix)
        ]


# ── save_config / load_config 基本行为 ───────────────────

class TestSaveLoadRoundtrip(ConfigTestBase):

    def test_save_then_load_roundtrip(self):
        payload = {
            "categories": [{"name": "图片", "extensions": ["png"], "folder": "图片"}],
            "desktop_path": self.tmp,
            "storage_path": self.tmp,
            "initialized": True,
            "theme": "emerald",
        }
        config.save_config(payload)
        got = config.load_config()
        self.assertEqual(got["initialized"], True)
        self.assertEqual(got["categories"], payload["categories"])
        self.assertEqual(got["storage_path"], self.tmp)

    def test_save_config_writes_valid_json(self):
        config.save_config({"a": 1, "中文": "值"})
        with open(self.config_path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
        self.assertEqual(parsed, {"a": 1, "中文": "值"})

    def test_load_creates_default_when_missing(self):
        self.assertFalse(os.path.exists(self.config_path))
        cfg = config.load_config()
        self.assertFalse(cfg["initialized"])
        self.assertEqual(cfg["categories"], config.DEFAULT_CONFIG["categories"])
        # 缺省时会把默认配置落盘
        self.assertTrue(os.path.exists(self.config_path))
        self.assertFalse(self.corrupt_backups())

    def test_load_fills_missing_default_keys(self):
        self.write_raw(json.dumps({"initialized": True}))
        cfg = config.load_config()
        for key in config.DEFAULT_CONFIG:
            self.assertIn(key, cfg)
        self.assertTrue(cfg["initialized"])

    def test_load_sets_default_desktop_when_empty(self):
        self.write_raw(json.dumps({"desktop_path": ""}))
        with mock.patch("config._get_default_desktop", return_value="X:/fake-desktop"):
            cfg = config.load_config()
        self.assertEqual(cfg["desktop_path"], "X:/fake-desktop")

    def test_valid_config_preserves_initialized_true(self):
        self.write_raw(json.dumps({"initialized": True}))
        cfg = config.load_config()
        self.assertTrue(cfg["initialized"])

    def test_valid_config_is_not_backed_up(self):
        self.write_raw(json.dumps({"initialized": True}))
        config.load_config()
        self.assertEqual(self.corrupt_backups(), [], "正常配置不应产生损坏备份")


# ── save_config 原子写 ───────────────────────────────────

class TestAtomicSave(ConfigTestBase):

    def test_failed_write_leaves_original_intact(self):
        config.save_config({"value": "original"})
        before = self.read_raw()
        with mock.patch("config.json.dump", side_effect=ValueError("disk full")):
            with self.assertRaises(ValueError):
                config.save_config({"value": "changed"})
        # 旧实现会先 open(...,'w') 截断文件，这里断言原子写保护了原内容
        self.assertEqual(self.read_raw(), before, "写入失败时原配置必须完好")

    def test_failed_write_leaves_no_temp_files(self):
        config.save_config({"value": "original"})
        with mock.patch("config.json.dump", side_effect=ValueError("disk full")):
            with self.assertRaises(ValueError):
                config.save_config({"value": "changed"})
        leftovers = [n for n in os.listdir(self.tmp) if n.startswith(".config-")]
        self.assertEqual(leftovers, [], "失败的临时文件必须清理干净")

    def test_successful_save_replaces_old_content(self):
        config.save_config({"value": "old"})
        config.save_config({"value": "new"})
        with open(self.config_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"value": "new"})
        leftovers = [n for n in os.listdir(self.tmp) if n.startswith(".config-")]
        self.assertEqual(leftovers, [], "成功写入后不应残留临时文件")


# ── 损坏配置：备份 + 保守地按「跑过」处理 ─────────────────
#
# AW-15：回退方向必须保守。**只有文件不存在才是首次运行**；
# 文件存在但读不出来 = 程序跑过 → initialized=True，绝不触发二次搬移。

class TestCorruptConfigRecovery(ConfigTestBase):

    def test_half_json_backs_up_corrupt_file(self):
        corrupt = '{\n  "initialized": true,\n  "categories": ['
        self.write_raw(corrupt)
        config.load_config()
        backups = self.corrupt_backups()
        self.assertEqual(len(backups), 1, "损坏配置必须备份一份")
        with open(backups[0], "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), corrupt, "备份内容必须等于原损坏内容")

    def test_half_json_preserves_initialized_true(self):
        self.write_raw('{\n  "initialized": true,\n  "categories": [')
        cfg = config.load_config()
        self.assertTrue(cfg["initialized"], "损坏配置必须保留 initialized=true")
        # 回退后的配置应重新落盘为合法 JSON
        self.assertTrue(json.loads(self.read_raw())["initialized"])

    def test_invalid_json_backs_up_corrupt_file(self):
        corrupt = "this is not json at all {{{"
        self.write_raw(corrupt)
        config.load_config()
        backups = self.corrupt_backups()
        self.assertEqual(len(backups), 1)
        with open(backups[0], "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), corrupt)

    def test_invalid_json_without_initialized_is_treated_as_ran(self):
        # 旧行为：捞不到 initialized → 回退 False（危险，会二次搬移）
        # 新行为：文件存在即视为「跑过」→ True
        self.write_raw("totally broken {{{")
        cfg = config.load_config()
        self.assertTrue(cfg["initialized"], "存在但读不出来的配置必须按「跑过」处理")

    def test_corrupt_config_with_initialized_false_is_still_treated_as_ran(self):
        # 即使损坏文本里写着 false，也不能据此重跑首次搬移：
        # 顶层 false 无法与「嵌套的无关 false」区分，且方向一旦搞错代价是搬两遍桌面。
        self.write_raw('{"initialized": false, "categories": [')
        cfg = config.load_config()
        self.assertTrue(cfg["initialized"], "损坏配置一律按「跑过」处理")

    def test_truncated_before_initialized_is_treated_as_ran(self):
        # 旧的非原子写最可能产生的损坏形态：截断在 initialized 之前。
        # 旧实现正则抢救返回 None → 回退 False → 二次搬移。
        self.write_raw('{"categories": [{"name": "图片", "extensions": ["png"]}')
        cfg = config.load_config()
        self.assertTrue(cfg["initialized"], "截断在 initialized 之前也必须按「跑过」处理")

    def test_nested_initialized_false_does_not_fool_recovery(self):
        # 旧实现用 re.search 取第一个匹配且不分层级 → 被嵌套的 false 骗到危险方向。
        self.write_raw(
            '{"nested": {"initialized": false}, "initialized": true, "categories": ['
        )
        cfg = config.load_config()
        self.assertTrue(cfg["initialized"], "不能被嵌套的 initialized=false 骗到")

    def test_nested_initialized_true_does_not_fool_recovery(self):
        self.write_raw(
            '{"nested": {"initialized": true}, "initialized": false, "categories": ['
        )
        cfg = config.load_config()
        self.assertTrue(cfg["initialized"], "存在但读不出来的一律按「跑过」处理")

    def test_undecodable_config_is_backed_up_and_treated_as_ran(self):
        blob = b"\xff\xfe\x00\x01\x02not-utf8"
        with open(self.config_path, "wb") as f:
            f.write(blob)

        cfg = config.load_config()

        self.assertTrue(cfg["initialized"], "无法解码的配置必须按「跑过」处理")
        backups = self.corrupt_backups()
        self.assertEqual(len(backups), 1, "无法解码的配置也必须备份")
        with open(backups[0], "rb") as f:
            self.assertEqual(f.read(), blob, "备份必须逐字节等于原损坏内容")

    def test_read_oserror_is_treated_as_ran(self):
        import builtins

        config.save_config({"initialized": True, "categories": []})
        real_open = builtins.open
        cfg_path = os.path.abspath(self.config_path)

        def flaky_open(path, mode="r", *args, **kwargs):
            if os.path.abspath(path) == cfg_path and "r" in mode and "b" not in mode:
                raise OSError("permission denied")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=flaky_open):
            cfg = config.load_config()

        self.assertTrue(cfg["initialized"], "读取报错时必须按「跑过」处理")

    def test_valid_json_that_is_not_an_object_is_treated_as_corrupt(self):
        # 合法 JSON 但不是对象（如 [] / null）→ 与损坏等价处理
        self.write_raw("[]")
        cfg = config.load_config()
        self.assertTrue(cfg["initialized"])
        self.assertEqual(len(self.corrupt_backups()), 1)

    def test_salvage_helper_is_gone(self):
        # AW-15(b)：正则抢救会被嵌套键骗到，已删除——少一段会骗人的代码。
        self.assertFalse(
            hasattr(config, "_salvage_initialized"),
            "_salvage_initialized 应已被删除（它会被嵌套键骗到危险方向）",
        )


# ── 端到端：损坏配置不得触发二次搬移 ──────────────────────
#
# 全程只在 tempfile.TemporaryDirectory() 内：假桌面 + 假存储根，
# config.CONFIG_PATH 已打桩到临时路径（init_folders 会调 save_config）。

class TestCorruptConfigDoesNotTriggerSecondMove(ConfigTestBase):

    def setUp(self):
        super().setUp()
        self.desktop = os.path.join(self.tmp, "Desktop")
        self.storage = os.path.join(self.tmp, "storage")
        os.makedirs(self.desktop)
        os.makedirs(self.storage)

    def _prepare(self, cfg):
        """把配置指向假桌面/假存储根，并放一个「本该被搬走」的文件。"""
        cfg["desktop_path"] = self.desktop
        cfg["storage_path"] = self.storage
        cfg["categories"] = [dict(c) for c in CATEGORIES]
        src = os.path.join(self.desktop, "report.doc")
        with open(src, "w", encoding="utf-8") as f:
            f.write("keep me")
        return src

    def _assert_no_second_move(self, src):
        self.assertTrue(os.path.exists(src), "损坏配置不得再次搬移桌面文件")
        self.assertFalse(
            os.path.exists(os.path.join(self.storage, "办公文件", "report.doc")),
            "损坏配置不应触发二次搬移",
        )
        # 全程只在临时目录内
        self.assertTrue(os.path.abspath(src).startswith(self.tmp))

    def test_corrupt_config_keeps_initialized_and_avoids_second_move(self):
        # 一份「已初始化过」但被写坏的配置（模拟写中断留下的半截 JSON）
        self.write_raw('{\n  "initialized": true,\n  "categories": [')

        cfg = config.load_config()
        src = self._prepare(cfg)
        file_manager.init_folders(cfg)

        # 先断言「没发生二次搬移」（可观测的损害），再断言 initialized 状态
        self._assert_no_second_move(src)
        self.assertTrue(cfg["initialized"], "损坏配置必须保留 initialized，避免二次搬移")

    def test_truncated_before_initialized_avoids_second_move(self):
        # AW-15 实测的损坏形态：截断在 initialized 之前（旧的非原子写最可能产生）
        self.write_raw('{"categories": [{"name": "办公文件", "extensions": ["doc"]}')

        cfg = config.load_config()
        src = self._prepare(cfg)
        file_manager.init_folders(cfg)

        self._assert_no_second_move(src)
        self.assertTrue(cfg["initialized"], "截断在 initialized 之前也必须按「跑过」处理")

    def test_nested_initialized_key_avoids_second_move(self):
        # 嵌套的 initialized=false 在前 → 旧的正则抢救会返回 False（危险方向）
        self.write_raw(
            '{"nested": {"initialized": false}, "initialized": true, "categories": ['
        )

        cfg = config.load_config()
        src = self._prepare(cfg)
        file_manager.init_folders(cfg)

        self._assert_no_second_move(src)
        self.assertTrue(cfg["initialized"])

    def test_undecodable_config_avoids_second_move(self):
        with open(self.config_path, "wb") as f:
            f.write(b"\xff\xfe\x00\x01not-utf8")

        cfg = config.load_config()
        src = self._prepare(cfg)
        file_manager.init_folders(cfg)

        self._assert_no_second_move(src)
        self.assertTrue(cfg["initialized"])

    def test_missing_config_is_still_treated_as_first_run(self):
        # 这条不能改坏：新装用户第一次跑必须仍然搬移桌面文件
        self.assertFalse(os.path.exists(self.config_path))

        cfg = config.load_config()
        self.assertFalse(cfg["initialized"], "文件不存在 = 真正的首次运行")

        src = self._prepare(cfg)
        file_manager.init_folders(cfg)

        moved = os.path.join(self.storage, "办公文件", "report.doc")
        self.assertTrue(os.path.isfile(moved), "首次运行必须把匹配文件搬进分类文件夹")
        self.assertFalse(os.path.exists(src), "首次运行后桌面上不应再有源文件")
        self.assertTrue(os.path.abspath(moved).startswith(self.tmp))


if __name__ == "__main__":
    unittest.main()
