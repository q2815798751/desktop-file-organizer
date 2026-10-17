"""
config.py 读写配置的单元测试（标准库 unittest，零新依赖）。

数据安全红线：CONFIG_PATH 在非打包状态下指向仓库根目录的 config.json。
本文件所有用例在 setUp 里 **先把 config.CONFIG_PATH 打桩到临时目录**，
保证绝不往仓库根目录写 config.json（跑完 git status 必须干净）。
所有文件操作都在 tempfile.TemporaryDirectory() 内，不导入 GUI 模块。

运行：python -m unittest discover -s tests -v
"""
import copy
import json
import os
import sys
import tempfile
import types
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


# ── AW-13：桌面图标重排开关 arrange_icons 的默认值 / 向后兼容 ──

class TestArrangeIconsDefault(ConfigTestBase):
    """
    AW-13 的配置层保证：`arrange_icons` 默认 True。

    老配置（没有这个键）经 `load_config` 补全缺失字段后必须拿到 True ——
    这是「向后兼容、不改变现有行为」在配置层的落点；显式设成 false 则必须保留。
    """

    def test_default_config_has_arrange_icons_true(self):
        self.assertIs(
            config.DEFAULT_CONFIG["arrange_icons"], True,
            "默认值必须为 True（保持现有行为，产品决策）",
        )

    def test_old_config_without_key_is_backfilled_true(self):
        # 一份「旧」配置：没有 arrange_icons
        self.write_raw(json.dumps({"initialized": True, "theme": "emerald"}))
        cfg = config.load_config()
        self.assertIs(
            cfg["arrange_icons"], True,
            "老配置缺 arrange_icons 时必须补成 True（仍然排列）",
        )

    def test_explicit_false_is_preserved(self):
        # 用户显式关掉 → load_config 不得把它改回 True
        self.write_raw(json.dumps({"arrange_icons": False}))
        cfg = config.load_config()
        self.assertIs(cfg["arrange_icons"], False)


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


# ── AW-10：返回的配置不得与模块级 DEFAULT_CONFIG 共享内层引用 ──
#
# 旧实现 `_default_config` 只做浅拷贝：`dict(DEFAULT_CONFIG)` 浅拷贝顶层，
# `[dict(c) for c in ...]` 浅拷贝每个分类字典的外层，于是
# categories[i]["subtypes"] / ["extensions"] 仍与 DEFAULT_CONFIG 共享引用。
# 运行时原地修改（append 扩展名、往 subtypes 加子类型）会永久污染
# DEFAULT_CONFIG，「恢复默认」拿到的是被改过的配置。

class TestDefaultConfigIsolation(ConfigTestBase):

    def _assert_default_unchanged(self, snapshot):
        self.assertEqual(
            config.DEFAULT_CONFIG, snapshot,
            "对返回配置的原地修改不得污染模块级 DEFAULT_CONFIG",
        )

    def test_returned_config_does_not_share_subtypes_with_default(self):
        cfg = config.load_config()
        self.assertIsNot(
            cfg["categories"][0]["subtypes"],
            config.DEFAULT_CONFIG["categories"][0]["subtypes"],
            "subtypes 必须是深拷贝，不能与 DEFAULT_CONFIG 共享引用",
        )
        self.assertIsNot(
            cfg["categories"][0]["extensions"],
            config.DEFAULT_CONFIG["categories"][0]["extensions"],
            "extensions 必须是深拷贝，不能与 DEFAULT_CONFIG 共享引用",
        )

    def test_in_place_subtype_mutation_does_not_pollute_default(self):
        snapshot = copy.deepcopy(config.DEFAULT_CONFIG)
        cfg = config.load_config()
        subtypes = cfg["categories"][0]["subtypes"]
        # 原地改内层：既有子类型追加 + 新增子类型键
        subtypes["Word文档"].append("POLLUTED")
        subtypes["注入的子类型"] = ["zzz"]
        cfg["categories"][0]["extensions"].append("POLLUTED_EXT")

        self._assert_default_unchanged(snapshot)
        self.assertNotIn("POLLUTED", config.DEFAULT_CONFIG["categories"][0]["subtypes"]["Word文档"])
        self.assertNotIn("注入的子类型", config.DEFAULT_CONFIG["categories"][0]["subtypes"])

    def test_reload_after_in_place_mutation_returns_clean_default(self):
        # 模拟「恢复默认」：删掉配置后重新 load_config 应拿到**干净**的默认值。
        cfg = config.load_config()
        cfg["categories"][0]["subtypes"]["Word文档"].append("POLLUTED")
        cfg["categories"][0]["subtypes"]["注入的子类型"] = ["zzz"]

        os.remove(self.config_path)
        fresh = config.load_config()

        self.assertNotIn("POLLUTED", fresh["categories"][0]["subtypes"]["Word文档"])
        self.assertNotIn("注入的子类型", fresh["categories"][0]["subtypes"])
        self.assertEqual(
            fresh["categories"][0]["subtypes"],
            config.DEFAULT_CONFIG["categories"][0]["subtypes"],
        )

    def test_missing_key_fill_does_not_share_default_references(self):
        # 配置文件存在但缺 "categories" → 补默认值时也不能共享引用
        self.write_raw(json.dumps({"initialized": True}))
        snapshot = copy.deepcopy(config.DEFAULT_CONFIG)
        cfg = config.load_config()

        self.assertIsNot(cfg["categories"], config.DEFAULT_CONFIG["categories"])
        self.assertIsNot(
            cfg["categories"][0]["subtypes"],
            config.DEFAULT_CONFIG["categories"][0]["subtypes"],
        )
        cfg["categories"].append({"name": "新分类", "extensions": ["x"], "folder": "新分类"})
        cfg["categories"][0]["subtypes"]["Word文档"].append("POLLUTED")

        self._assert_default_unchanged(snapshot)
        self.assertEqual(len(config.DEFAULT_CONFIG["categories"]), 5, "默认分类数量不得被改动")


# ── AW-12：开机自启的 pywin32 降级行为 ───────────────────────
# README「环境要求」里写明：未安装可选的 pywin32 时，开机自启会降级成启动文件夹里的
# .bat（仍可用，只是登录时闪现控制台窗口）。这里把这条**被文档承诺的行为**钉住——
# 否则文档一旦与代码漂移，没人会发现（正是 AW-12 要修的那类「文档与实物不一致」）。
#
# ⚠️ STARTUP_LNK 在非打包状态下指向**真实的** %APPDATA%\...\Startup，
#    所以本类在 setUp 里把它打桩到临时目录，**绝不真的创建开机自启快捷方式**。

class AutoStartTestBase(ConfigTestBase):
    """把启动文件夹路径打桩到临时目录。"""

    def setUp(self):
        super().setUp()
        self.startup_lnk = os.path.join(self.tmp, "DesktopOrganizer.lnk")
        patcher = mock.patch("config.STARTUP_LNK", self.startup_lnk)
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def startup_bat(self):
        return self.startup_lnk.replace(".lnk", ".bat")

    def assert_paths_inside_tmp(self):
        """护栏：任何启动路径落到临时目录外就立即中止（红线：不碰真实启动文件夹）。"""
        for p in (self.startup_lnk, self.startup_bat):
            self.assertTrue(
                os.path.abspath(p).startswith(os.path.abspath(self.tmp) + os.sep),
                f"启动路径 {p} 不在临时目录 {self.tmp} 内，拒绝继续（会碰到真实启动文件夹）",
            )


class TestAutoStartFallback(AutoStartTestBase):
    """没有 pywin32 时降级写 .bat（README 描述的行为）。"""

    def _without_pywin32(self):
        # sys.modules 里放 None → `import pythoncom` 抛 ImportError（本机已装 pywin32，
        # 必须这样屏蔽掉，才能测降级分支）。
        return mock.patch.dict(
            sys.modules,
            {"pythoncom": None, "win32com": None, "win32com.client": None},
        )

    def test_missing_pywin32_falls_back_to_bat(self):
        self.assert_paths_inside_tmp()
        with self._without_pywin32():
            config._create_startup_shortcut()

        self.assertTrue(os.path.exists(self.startup_bat), "缺失 pywin32 时应写出 .bat")
        self.assertFalse(os.path.exists(self.startup_lnk), "缺失 pywin32 时不应有 .lnk")
        with open(self.startup_bat, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(sys.executable, content)
        self.assertIn("main.py", content)

    def test_get_auto_start_detects_bat(self):
        # 降级产物（.bat）也必须被算作「已开启自启」，否则托盘勾选状态会错。
        self.assert_paths_inside_tmp()
        with open(self.startup_bat, "w", encoding="utf-8") as f:
            f.write("@echo off\n")
        self.assertTrue(config.get_auto_start())

    def test_get_auto_start_false_when_neither_exists(self):
        self.assert_paths_inside_tmp()
        self.assertFalse(config.get_auto_start())

    def test_set_auto_start_false_removes_bat_and_lnk(self):
        self.assert_paths_inside_tmp()
        for p in (self.startup_lnk, self.startup_bat):
            with open(p, "w", encoding="utf-8") as f:
                f.write("x")
        config.set_auto_start(False)
        self.assertFalse(os.path.exists(self.startup_lnk))
        self.assertFalse(os.path.exists(self.startup_bat))


class TestAutoStartWithPywin32(AutoStartTestBase):
    """装了 pywin32 时走 .lnk 分支（注入假模块，不碰真实 COM / 注册表 / 启动文件夹）。"""

    def test_uses_lnk_when_pywin32_available(self):
        self.assert_paths_inside_tmp()
        calls = []

        pythoncom = types.ModuleType("pythoncom")
        pythoncom.CoInitialize = lambda: calls.append("init")
        pythoncom.CoUninitialize = lambda: calls.append("uninit")

        win32com = types.ModuleType("win32com")
        client = types.ModuleType("win32com.client")

        class _Shortcut:
            def __init__(self, path):
                self._path = path

            def Save(self):
                with open(self._path, "w", encoding="utf-8") as f:
                    f.write("fake lnk")

        class _Shell:
            def CreateShortCut(self, path):
                calls.append(("cut", path))
                return _Shortcut(path)

        client.Dispatch = lambda progid: calls.append(("dispatch", progid)) or _Shell()
        win32com.client = client

        with mock.patch.dict(
            sys.modules,
            {"pythoncom": pythoncom, "win32com": win32com, "win32com.client": client},
        ):
            config._create_startup_shortcut()

        self.assertIn("init", calls)
        self.assertIn("uninit", calls)
        self.assertIn(("dispatch", "WScript.Shell"), calls)
        self.assertIn(("cut", self.startup_lnk), calls)  # 目标正是 .lnk 路径
        self.assertTrue(os.path.exists(self.startup_lnk), "装了 pywin32 时应创建 .lnk")
        self.assertFalse(os.path.exists(self.startup_bat), "装了 pywin32 时不应再写 .bat")


if __name__ == "__main__":
    unittest.main()
