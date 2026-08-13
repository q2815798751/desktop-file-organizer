"""
配置管理模块 — 读写 config.json，管理分类规则和面板状态。
"""
import json
import os
import sys

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


def load_config():
    """加载配置，不存在则创建默认配置。"""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 补全缺失的默认字段
            for key, val in DEFAULT_CONFIG.items():
                if key not in cfg:
                    cfg[key] = val
            if not cfg.get("desktop_path"):
                cfg["desktop_path"] = _get_default_desktop()
            return cfg
        except (json.JSONDecodeError, IOError):
            pass

    cfg = dict(DEFAULT_CONFIG)
    cfg["desktop_path"] = _get_default_desktop()
    # deep copy categories
    cfg["categories"] = [dict(c) for c in DEFAULT_CONFIG["categories"]]
    save_config(cfg)
    return cfg


def save_config(cfg):
    """保存配置到 JSON 文件。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


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
