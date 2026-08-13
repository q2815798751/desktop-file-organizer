"""
文件管理模块 — 文件分类、移动、列出。
"""
import os
import shutil
import ctypes
from ctypes import wintypes
from datetime import datetime

# 分类文件夹的默认存储位置：Documents\桌面文件收纳（不在桌面，保持桌面整洁）
DEFAULT_STORAGE_NAME = "桌面文件收纳"


def get_desktop_path(config):
    """获取桌面路径（确保目录存在）。"""
    path = config.get("desktop_path", "")
    if not path or not os.path.isdir(path):
        path = os.path.join(os.path.expanduser("~"), "Desktop")
    return path


def get_storage_root(config):
    """分类文件夹的存储根目录（config.storage_path，缺省 Documents\\桌面文件收纳）。"""
    root = config.get("storage_path", "")
    if root:
        return root
    return os.path.join(os.path.expanduser("~"), "Documents", DEFAULT_STORAGE_NAME)


def get_category_folder(config, category):
    """获取分类对应的子文件夹完整路径（位于存储根目录下，而非桌面）。"""
    folder_name = category.get("folder", category["name"])
    return os.path.join(get_storage_root(config), folder_name)


def init_folders(config):
    """
    初始化分类文件夹：
    1. 确保所有分类子文件夹存在（每次启动都执行）
    2. 仅首次运行时把桌面上已有的匹配文件移入对应文件夹
       （用 config 里的 initialized 标记，避免每次启动都静默移动文件）
    """
    desktop = get_desktop_path(config)
    first_run = not config.get("initialized", False)

    for cat in config["categories"]:
        folder = get_category_folder(config, cat)
        os.makedirs(folder, exist_ok=True)

        if first_run:
            extensions = cat.get("extensions", [])
            _move_matching_files(desktop, folder, extensions)

    if first_run:
        config["initialized"] = True
        from config import save_config
        save_config(config)

    return 0


def categorize_file(file_path, config):
    """
    根据扩展名将文件移动到对应分类文件夹。
    返回 (category_name, new_path) 或 (None, None) 如果无匹配。
    """
    if not os.path.isfile(file_path):
        return None, None

    desktop = get_desktop_path(config)
    # 只处理桌面根目录下的文件，不处理子文件夹中的文件
    parent_dir = os.path.dirname(os.path.abspath(file_path))
    if os.path.normpath(parent_dir) != os.path.normpath(desktop):
        return None, None

    ext = os.path.splitext(file_path)[1].lower().lstrip(".")

    for cat in config["categories"]:
        extensions = [e.lower().lstrip(".") for e in cat.get("extensions", [])]
        if ext in extensions:
            folder = get_category_folder(config, cat)
            os.makedirs(folder, exist_ok=True)

            dest = _resolve_conflict(folder, os.path.basename(file_path))
            try:
                shutil.move(file_path, dest)
                return cat["name"], dest
            except (OSError, shutil.Error):
                return None, None

    return None, None


def get_files_in_category(config, category):
    """
    列出分类文件夹中的顶层条目（文件 + 子文件夹），按修改时间降序排列。
    返回 [(full_path, name, mtime_datetime), ...]。子文件夹用 isdir 判断。
    """
    folder = get_category_folder(config, category)
    if not os.path.isdir(folder):
        return []

    files = []
    try:
        for entry in os.listdir(folder):
            full = os.path.join(folder, entry)
            # 同时包含子文件夹（如「其他」里的项目文件夹）与普通文件
            mtime = os.path.getmtime(full)
            files.append((full, entry, datetime.fromtimestamp(mtime)))
    except OSError:
        return []

    # 按修改时间降序（最新的在前）
    files.sort(key=lambda x: x[2], reverse=True)
    return files


def _move_matching_files(source_dir, target_dir, extensions):
    """将源目录中匹配扩展名的文件移动到目标目录。"""
    for entry in os.listdir(source_dir):
        full = os.path.join(source_dir, entry)
        if not os.path.isfile(full):
            continue
        ext = os.path.splitext(entry)[1].lower().lstrip(".")
        if ext in [e.lower().lstrip(".") for e in extensions]:
            dest = _resolve_conflict(target_dir, entry)
            try:
                shutil.move(full, dest)
            except (OSError, shutil.Error):
                pass


def move_into_category(config, category, src_path):
    """
    把外部文件/文件夹移入指定分类的存储文件夹（拖拽收纳用）。
    返回 (name, dest) 或 (None, None)。防护：拒绝移动分类文件夹本身 / 存储根，
    跳过已在目标分类内的条目。
    """
    if not os.path.exists(src_path):
        return None, None

    folder = get_category_folder(config, category)
    src_abs = os.path.abspath(src_path)
    folder_abs = os.path.abspath(folder)

    # 已在目标分类内 → 跳过
    try:
        if os.path.commonpath([src_abs, folder_abs]) == folder_abs:
            return None, None
    except ValueError:
        pass  # 不同盘符，不在此判断

    # 源是分类文件夹或存储根 → 拒绝
    cat_folders = {
        os.path.abspath(get_category_folder(config, c))
        for c in config.get("categories", [])
    }
    if src_abs in cat_folders or src_abs == os.path.abspath(get_storage_root(config)):
        return None, None

    os.makedirs(folder, exist_ok=True)
    dest = _resolve_conflict(folder, os.path.basename(src_path))
    try:
        shutil.move(src_path, dest)
        return os.path.basename(dest), dest
    except (OSError, shutil.Error):
        return None, None


def _resolve_conflict(folder, filename):
    """处理文件名冲突：文档.docx → 文档(1).docx"""
    dest = os.path.join(folder, filename)
    if not os.path.exists(dest):
        return dest

    name, ext = os.path.splitext(filename)
    counter = 1
    while True:
        new_name = f"{name}({counter}){ext}"
        new_dest = os.path.join(folder, new_name)
        if not os.path.exists(new_dest):
            return new_dest
        counter += 1


# ── 桌面图标排列 ─────────────────────────────────────────

def arrange_desktop_icons():
    """自动排列桌面图标（对齐网格）。best-effort，失败静默返回 False。"""
    try:
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = wintypes.LPARAM
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        LVM_ARRANGE = 0x1016
        LVA_SNAPTOGRID = 0x5

        def find_listview(hwnd):
            """在 hwnd 下找 SHELLDLL_DefView → SysListView32。"""
            defview = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
            if defview:
                return user32.FindWindowExW(defview, 0, "SysListView32", None)
            return 0

        found = []

        def enum_cb(hwnd, _lparam):
            lv = find_listview(hwnd)
            if lv:
                found.append(lv)
                return False  # 停止枚举
            return True

        # 主路径：Progman 下
        progman = user32.FindWindowW("Progman", None)
        if progman:
            lv = find_listview(progman)
            if lv:
                found.append(lv)

        # 兜底：Win+D / 幻灯片壁纸等情况下枚举顶层窗口
        if not found:
            user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

        if found:
            user32.SendMessageW(found[0], LVM_ARRANGE, LVA_SNAPTOGRID, 0)
            return True
    except Exception:
        pass
    return False
