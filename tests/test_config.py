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


# ── 损坏配置：备份 + 保留 initialized ─────────────────────

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

    def test_invalid_json_without_initialized_falls_back_to_false(self):
        # 捞不到 initialized → 保持默认 False（真正的首次运行仍应初始化）
        self.write_raw("totally broken {{{")
        cfg = config.load_config()
        self.assertFalse(cfg["initialized"])

    def test_corrupt_config_preserves_initialized_false(self):
        self.write_raw('{"initialized": false, "categories": [')
        cfg = config.load_config()
        self.assertFalse(cfg["initialized"])


# ── 端到端：损坏配置不得触发二次搬移 ──────────────────────

class TestCorruptConfigDoesNotTriggerSecondMove(ConfigTestBase):

    def setUp(self):
        super().setUp()
        self.desktop = os.path.join(self.tmp, "Desktop")
        self.storage = os.path.join(self.tmp, "storage")
        os.makedirs(self.desktop)
        os.makedirs(self.storage)

    def test_corrupt_config_keeps_initialized_and_avoids_second_move(self):
        # 一份「已初始化过」但被写坏的配置（模拟写中断留下的半截 JSON）
        self.write_raw('{\n  "initialized": true,\n  "categories": [')

        cfg = config.load_config()
        self.assertTrue(cfg["initialized"], "损坏配置必须保留 initialized，避免二次搬移")

        cfg["desktop_path"] = self.desktop
        cfg["storage_path"] = self.storage
        cfg["categories"] = [dict(c) for c in CATEGORIES]

        # 桌面上放一个本该被搬走的文件
        src = os.path.join(self.desktop, "report.doc")
        with open(src, "w", encoding="utf-8") as f:
            f.write("keep me")

        file_manager.init_folders(cfg)

        self.assertTrue(os.path.exists(src), "initialized=true 时不得再次搬移桌面文件")
        self.assertFalse(
            os.path.exists(os.path.join(self.storage, "办公文件", "report.doc")),
            "损坏配置不应触发二次搬移",
        )
        # 全程只在临时目录内
        self.assertTrue(os.path.abspath(src).startswith(self.tmp))


if __name__ == "__main__":
    unittest.main()
