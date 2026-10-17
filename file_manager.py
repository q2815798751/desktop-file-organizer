"""
文件管理模块 — 文件分类、移动、列出。
"""
import errno
import os
import shutil
import ctypes
from collections import namedtuple
from ctypes import wintypes
from datetime import datetime

# 分类文件夹的默认存储位置：Documents\桌面文件收纳（不在桌面，保持桌面整洁）
DEFAULT_STORAGE_NAME = "桌面文件收纳"

# 一次搬移的结果（结构化：成功/失败 + 原因），替代「失败时静默返回 None」。
MoveResult = namedtuple("MoveResult", ["ok", "path", "error"])

# 一批搬移的统计（成功数 / 失败数 / 失败原因列表），供 init_folders 汇总上报。
MoveStats = namedtuple("MoveStats", ["moved", "failed", "errors"])

# 竞态下换名重试上限：_resolve_conflict 已保证正常情况不冲突，
# 这里只兜底「解析出目标名之后、原子占用之前被别的进程抢占」的极窄窗口。
_CONFLICT_RETRIES = 100


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

    返回 MoveStats(moved, failed, errors)：首次运行搬移的统计。
    搬移失败不再被静默吞掉，调用方可以据此提示用户。
    """
    desktop = get_desktop_path(config)
    first_run = not config.get("initialized", False)

    moved = 0
    failed = 0
    errors = []

    for cat in config["categories"]:
        folder = get_category_folder(config, cat)
        os.makedirs(folder, exist_ok=True)

        if first_run:
            extensions = cat.get("extensions", [])
            stats = _move_matching_files(desktop, folder, extensions)
            moved += stats.moved
            failed += stats.failed
            errors.extend(stats.errors)

    if first_run:
        config["initialized"] = True
        from config import save_config
        save_config(config)

    return MoveStats(moved, failed, errors)


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

            result = _move_no_clobber(file_path, folder, os.path.basename(file_path))
            if result.ok:
                return cat["name"], result.path
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
    """
    将源目录中匹配扩展名的文件移动到目标目录。

    返回 MoveStats(moved, failed, errors)：搬移失败不再被静默吞掉，
    调用方（init_folders 等）据此统计失败数。
    """
    moved = 0
    errors = []

    try:
        entries = os.listdir(source_dir)
    except OSError as e:
        return MoveStats(0, 0, [e])

    os.makedirs(target_dir, exist_ok=True)
    wanted = [e.lower().lstrip(".") for e in extensions]

    for entry in entries:
        full = os.path.join(source_dir, entry)
        if not os.path.isfile(full):
            continue
        ext = os.path.splitext(entry)[1].lower().lstrip(".")
        if ext in wanted:
            result = _move_no_clobber(full, target_dir, entry)
            if result.ok:
                moved += 1
            else:
                errors.append(result.error)

    return MoveStats(moved, len(errors), errors)


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
    result = _move_no_clobber(src_path, folder, os.path.basename(src_path))
    if result.ok:
        return os.path.basename(result.path), result.path
    return None, None


def _resolve_conflict(folder, filename):
    """
    处理文件名冲突：文档.docx → 文档(1).docx

    只负责**提议**一个当前不冲突的名字（纯函数，无副作用）。
    真正的安全性由 _move_no_clobber 保证：它会在搬移前用
    O_CREAT|O_EXCL / os.rename 原子地占用该路径，因此「提议」与
    「落盘」之间即使被别的进程抢占，也不会覆盖别人的文件。
    """
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


def _release_placeholder(dest, is_dir):
    """撤掉未被使用的占位（仅当它还是空的），避免留下垃圾文件。"""
    try:
        if is_dir:
            if not os.listdir(dest):
                os.rmdir(dest)
        elif os.path.getsize(dest) == 0:
            os.remove(dest)
    except OSError:
        pass


def _move_file_no_clobber(src, dest):
    """
    文件：先用 O_CREAT|O_EXCL 原子占位，再搬入占位处。
    目标已被别人占用时抛 FileExistsError（交由上层换名重试），
    因此绝不可能覆盖已存在的同名文件——这正是原来「先查存在再 move」
    之间那条竞态窗口会造成的数据丢失。
    """
    fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        shutil.move(src, dest)
    except BaseException:
        _release_placeholder(dest, is_dir=False)
        raise


def _move_dir_no_clobber(src, dest):
    """
    目录：os.rename 原子且不覆盖（目标已存在则 FileExistsError）。
    跨盘符（EXDEV）时退回 copytree：它用 os.makedirs 原子占用目标名，
    已存在同样抛 FileExistsError，因此不会覆盖或嵌套。
    """
    try:
        os.rename(src, dest)
        return
    except FileExistsError:
        raise
    except OSError as e:
        if getattr(e, "errno", None) != errno.EXDEV:
            raise
    # 跨盘符
    shutil.copytree(src, dest)
    shutil.rmtree(src)


def _move_no_clobber(src, folder, filename):
    """
    把 src 移入 folder，自动消解重名冲突，返回 MoveResult(ok, path, error)。

    与旧的「_resolve_conflict 之后直接 shutil.move」不同：
    - 名字是**原子占用**的，杜绝 TOCTOU 竞态覆盖；
    - 任何失败都以结构化结果返回（含原因），绝不静默吞掉。
    """
    is_dir = os.path.isdir(src)
    last_error = None

    for _ in range(_CONFLICT_RETRIES):
        dest = _resolve_conflict(folder, filename)
        try:
            if is_dir:
                _move_dir_no_clobber(src, dest)
            else:
                _move_file_no_clobber(src, dest)
            return MoveResult(True, dest, None)
        except FileExistsError as e:
            # 竞态：目标在解析之后被别人抢占 → 换个名字重试
            last_error = e
            continue
        except (OSError, shutil.Error) as e:
            return MoveResult(False, None, e)

    return MoveResult(
        False, None, last_error or OSError("目标目录同名条目过多，无法消解冲突")
    )


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
