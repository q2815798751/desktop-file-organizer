"""
配置管理模块 — 读写 config.json，管理分类规则和面板状态。
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

# PyInstaller 打包后把配置写在 exe 所在目录，方便写与查找
if getattr(sys, "frozen", False):
    CONFIG_DIR = os.path.dirname(sys.executable)
else:
    CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# Windows 启动文件夹
STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup",
)
STARTUP_LNK = os.path.join(STARTUP_DIR, "DesktopOrganizer.lnk")

DEFAULT_CONFIG = {
    "categories": [
        {
            # 办公文件：三个子类型共用一个文件夹，仅在应用内部区分
            "name": "办公文件",
            "extensions": ["doc", "docx", "xls", "xlsx", "csv", "pdf"],
            "folder": "办公文件",
            "subtypes": {
                "Word文档": ["doc", "docx"],
                "Excel表格": ["xls", "xlsx", "csv"],
                "PDF文件": ["pdf"],
            },
        },
        {"name": "压缩包", "extensions": ["zip", "rar", "7z"], "folder": "压缩包"},
        {"name": "文本文件", "extensions": ["txt", "md", "log"], "folder": "文本文件"},
        {"name": "图片", "extensions": ["jpg", "jpeg", "png", "gif", "bmp", "svg"], "folder": "图片"},
        # 其他：存放用户自建文件夹等，不做自动归类
        {"name": "其他", "extensions": [], "folder": "其他"},
    ],
    "panels": [],
    "desktop_path": "",
    "storage_path": "",
    "auto_start": False,
    "initialized": False,
    "theme": "emerald",
    "panel_opacity": 1.0,
    "font_scale": 1.0,
}


def _get_default_desktop():
    """获取当前用户的桌面路径。"""
    home = os.path.expanduser("~")
    return os.path.join(home, "Desktop")


def _default_config():
    """构造一份默认配置（补齐 desktop_path，复制 categories 外层字典）。"""
    cfg = dict(DEFAULT_CONFIG)
    cfg["desktop_path"] = _get_default_desktop()
    # copy categories（浅拷贝外层，保持既有行为）
    cfg["categories"] = [dict(c) for c in DEFAULT_CONFIG["categories"]]
    return cfg


def _backup_corrupt_config():
    """把损坏的配置文件备份成 config.json.corrupt-<时间戳>，返回备份路径或 None。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = f"{CONFIG_PATH}.corrupt-{stamp}"
    try:
        shutil.copyfile(CONFIG_PATH, backup_path)
    except OSError:
        return None
    return backup_path


def _atomic_write_json(path, cfg):
    """先写同目录下的临时文件，再 os.replace 原子替换，避免半截 JSON。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # 任何失败都不能破坏原文件，清理临时文件后原样抛出
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def load_config():
    """
    加载配置，不存在则创建默认配置。

    **首次运行 vs 配置损坏** 是这里唯一重要的一对分支：

    - 配置文件**不存在** → 真的是首次运行，返回默认配置（initialized=False），
      之后 init_folders 会做一次首次搬移。
    - 配置文件**存在但读不出来**（半截 JSON / 非法 JSON / 非 UTF-8 字节 / 读取报错）
      → 先把损坏文件备份成 config.json.corrupt-<时间戳>，再回退默认值，但
      **把 initialized 强制置为 True**。

    为什么损坏时必须按「跑过」处理：initialized=False 的语义是「从没运行过」，
    会让 init_folders 把**整个桌面再搬一次**（文件被改名成 name(1).ext）。
    而「配置文件存在」这件事本身就证明程序至少跑过一次——首次运行时
    load_config 会立刻把默认配置落盘。所以宁可少搬（用户可手动整理），
    也不能二次搬移（会打乱用户文件）。

    注意：这里**不再**从损坏文本里正则抢救 initialized。那种抢救用 re.search
    取第一个匹配且不分层级，会被无关的嵌套键（{"nested": {"initialized": false}}）
    骗到危险方向；而「文件存在即视为跑过」比它可靠得多，抢救已无必要。
    """
    if os.path.exists(CONFIG_PATH):
        cfg = None
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.loads(f.read())
        except (OSError, UnicodeDecodeError, ValueError):
            cfg = None

        if isinstance(cfg, dict):
            # 补全缺失的默认字段
            for key, val in DEFAULT_CONFIG.items():
                if key not in cfg:
                    cfg[key] = val
            if not cfg.get("desktop_path"):
                cfg["desktop_path"] = _get_default_desktop()
            return cfg

        # 文件存在但读不出来 / 不是 JSON 对象 → 视为损坏
        _backup_corrupt_config()
        cfg = _default_config()
        cfg["initialized"] = True
        save_config(cfg)
        return cfg

    cfg = _default_config()
    save_config(cfg)
    return cfg


def save_config(cfg):
    """保存配置到 JSON 文件（原子写：临时文件 + os.replace）。"""
    _atomic_write_json(CONFIG_PATH, cfg)


def get_auto_start():
    """检查是否已设置开机自启（.lnk 或回退的 .bat 任一生效）。"""
    return os.path.exists(STARTUP_LNK) or os.path.exists(STARTUP_LNK.replace(".lnk", ".bat"))


def set_auto_start(enabled):
    """启用或禁用开机自启（创建/删除启动文件夹快捷方式）。"""
    if enabled:
        _create_startup_shortcut()
    else:
        for p in (STARTUP_LNK, STARTUP_LNK.replace(".lnk", ".bat")):
            if os.path.exists(p):
                os.remove(p)


def _create_startup_shortcut():
    """在 Windows 启动文件夹中创建快捷方式。"""
    try:
        import pythoncom
        from win32com.client import Dispatch

        pythoncom.CoInitialize()
        try:
            shell = Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(STARTUP_LNK)
            shortcut.TargetPath = sys.executable
            shortcut.Arguments = f'"{os.path.join(CONFIG_DIR, "main.py")}"'
            shortcut.WorkingDirectory = CONFIG_DIR
            shortcut.Description = "Desktop File Organizer"
            shortcut.Save()
        finally:
            pythoncom.CoUninitialize()
    except ImportError:
        # 如果没有 pywin32，回退到创建 .bat 文件方式
        bat_path = STARTUP_LNK.replace(".lnk", ".bat")
        with open(bat_path, "w") as f:
            f.write(f'@echo off\n"{sys.executable}" "{os.path.join(CONFIG_DIR, "main.py")}"\n')
