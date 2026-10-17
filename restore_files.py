"""
恢复脚本 — 将存储目录中分类文件夹的文件移回桌面。
在需要还原文件时运行此脚本。

AW-6 修复（数据安全）：
- **目标桌面不再写死 `~/Desktop`**，而是读 `config.load_config()` 的 `desktop_path`。
  桌面被 OneDrive 等重定向到别处时，旧写法会把文件恢复到错误位置。
- **分类清单不再硬编码 5 个默认名**，而是遍历配置里的**实际分类**（含用户自建分类）。
  磁盘目录名取分类的 `folder` 字段（可与显示名 `name` 不一致），缺失时退回 `name`；
  旧写法导致用户自建分类里的文件永远恢复不了。
- 「计算恢复计划」抽成**纯函数** `build_restore_plan`（只读文件系统、绝不移动文件），
  便于在临时目录里单测；真正执行搬移的只有 `restore()`。

⚠️ 本脚本会**真实移动文件**。测试必须全程在 `tempfile.TemporaryDirectory()` 里跑，
并用 `unittest.mock.patch("config.CONFIG_PATH", <临时路径>)` 打桩配置路径。
"""
import os
import shutil

import config

# 与 config / file_manager 保持一致的默认值
_DEFAULT_STORAGE_NAME = "桌面文件收纳"


def resolve_desktop(cfg):
    """
    目标桌面目录：取 `config["desktop_path"]`；为空时回退 `~/Desktop`
    （与 `file_manager.get_desktop_path` 的缺省行为一致）。
    """
    desktop = (cfg or {}).get("desktop_path") or ""
    if desktop:
        return desktop
    return os.path.join(os.path.expanduser("~"), "Desktop")


def resolve_storage_root(cfg):
    """存储根目录：取 `config["storage_path"]`；为空时回退 `Documents\\桌面文件收纳`。"""
    root = (cfg or {}).get("storage_path") or ""
    if root:
        return root
    return os.path.join(os.path.expanduser("~"), "Documents", _DEFAULT_STORAGE_NAME)


def category_folders(cfg):
    """
    遍历配置里**实际的**分类，返回 `[(显示名, 磁盘目录名), ...]`。

    - 磁盘目录名取分类的 `folder` 字段（**可与显示名 `name` 不一致**）；
      `folder` 缺失或为空时退回 `name`。这就是「自建分类」能被恢复的关键：
      旧脚本只认 5 个写死的默认目录名，自建分类的文件永远扫描不到。
    - 按目录名去重（多个分类共用同一目录时只扫描一次），保持配置顺序。
    - 跳过名字不是非空文本的分类（含 `folder` 为非字符串的坏配置）。
    """
    result = []
    seen = set()
    for cat in (cfg or {}).get("categories") or []:
        if not isinstance(cat, dict):
            continue
        name = cat.get("name")
        folder = cat.get("folder") or name
        if not isinstance(folder, str) or not folder.strip():
            continue
        folder = folder.strip()
        if folder in seen:
            continue
        seen.add(folder)
        label = name.strip() if isinstance(name, str) and name.strip() else folder
        result.append((label, folder))
    return result


def _category_dir(root, folder):
    """
    把分类目录名解析成 `root` 内的完整路径；越界（绝对路径，或 `..` 逃出 root）返回 `None`。

    旧脚本的目录名是写死的、天然安全；改成配置驱动后必须自己兜住这层，
    否则手工编辑的 `folder`（如 `..\\..\\evil`）会让脚本扫描存储根之外并把那里的文件搬回桌面。
    """
    root_abs = os.path.abspath(root)
    if os.path.isabs(folder):
        return None
    target = os.path.abspath(os.path.join(root_abs, folder))
    try:
        # 用 commonpath 而不是 startswith（避免 `...\sub\stor` 这类前缀兄弟目录误判）
        if os.path.commonpath([target, root_abs]) != root_abs or target == root_abs:
            return None
    except ValueError:
        return None
    return target


def build_restore_plan(cfg):
    """
    纯函数（只读文件系统、**绝不移动文件**）：根据配置算出恢复计划。

    返回 `(desktop, entries)`：

    - `desktop` —— 目标桌面目录，来自 `config["desktop_path"]`
      （**不是写死的 `~/Desktop`**）。
    - `entries` —— `[(category_label, src_path, dest_dir, filename), ...]`，
      按分类顺序、文件名字典序排列；`dest_dir` 恒等于 `desktop`。

    判定规则：遍历配置里的实际分类（含自建分类）→ 解析出存储根下的分类目录
    （`folder` 字段，可与显示名不一致；越界的分类跳过）→ 目录不存在则跳过 →
    只收**普通文件**（不递归子目录）。
    """
    desktop = resolve_desktop(cfg)
    root = resolve_storage_root(cfg)
    entries = []
    for label, folder in category_folders(cfg):
        folder_path = _category_dir(root, folder)
        if folder_path is None or not os.path.isdir(folder_path):
            continue
        for entry in sorted(os.listdir(folder_path)):
            src = os.path.join(folder_path, entry)
            if os.path.isfile(src):
                entries.append((label, src, desktop, entry))
    return desktop, entries


def _resolve_dest(desktop, filename):
    """目标路径；桌面已有同名文件时改用 `<name>_restored(<n>)<ext>`（与原行为一致）。"""
    dest = os.path.join(desktop, filename)
    if not os.path.exists(dest):
        return dest
    name, ext = os.path.splitext(filename)
    counter = 1
    while True:
        dest = os.path.join(desktop, f"{name}_restored({counter}){ext}")
        if not os.path.exists(dest):
            return dest
        counter += 1


def restore():
    """执行恢复：读配置 → 算计划 → 逐个搬回 `desktop_path` 指向的桌面。"""
    cfg = config.load_config()
    root = resolve_storage_root(cfg)
    desktop, entries = build_restore_plan(cfg)
    print(f"从存储目录恢复: {root}")
    print(f"恢复到桌面: {desktop}\n")

    count = 0
    for label, src, dest_dir, filename in entries:
        dest = _resolve_dest(dest_dir, filename)
        try:
            shutil.move(src, dest)
            print(f"  已恢复[{label}]: {filename}")
            count += 1
        except OSError as e:
            print(f"  失败: {filename} - {e}")

    print(f"\n共恢复 {count} 个文件到桌面。")


if __name__ == "__main__":
    print("正在将文件从存储目录移回桌面...\n")
    restore()
