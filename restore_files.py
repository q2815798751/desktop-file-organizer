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

AW-21 修复（数据安全）：
- **junction / 符号链接逃逸复检**：`_category_dir` 在词法校验之后，复用
  `file_manager.realpath_escape_error` 做 `realpath` 复检。若 `storage_root\\<folder>`
  已存在且是指向根外的 junction（`mklink /J` 免管理员）或符号链接，**词法校验会放行、
  文件实际会被搬到存储根之外**（复查已用 `mklink /J` 实测复现：`restore()` 会把
  `<根外>\\SECRET.txt` 搬回桌面）。复检拒绝该分类，并记 WARNING 日志（可见降级，不静默）。
- **分类目录名去重按 `os.path.abspath`**：旧实现按原始字符串去重，`shared` 与 `.\\shared`
  这类等价拼写不会去重，导致计划里同一文件出现两次。

AW-8 修复（健壮性）：
- **读配置失败不再静默用默认路径**：`restore()` 经 `_load_config_or_default()` 读配置，
  失败时记一条 WARNING 再回退空配置（→ 默认路径 + 空分类清单 → 一个文件都不动）。
  旧实现 `except Exception: pass` 让「配置没读到」这件事无人知晓。

⚠️ 本脚本会**真实移动文件**。测试必须全程在 `tempfile.TemporaryDirectory()` 里跑。
  ⚠️ `mock.patch("config.CONFIG_PATH", <临时路径>)` **只对当前写法有效**——因为本脚本
  通过 `config.load_config()` 在**调用时**读模块全局 `config.CONFIG_PATH`。若哪天把配置
  路径改回**本模块自己的模块级常量**（AW-6 之前的写法），这个 patch 会**静默失效**，
  测试就会去读仓库根的 `config.json`。测试侧的护栏见 `tests/test_restore_files.py`
  的 `RestoreTestBase.setUp`（显式断言回退桌面落在临时目录内）。
"""
import logging
import os
import shutil

import config
import file_manager

logger = logging.getLogger(__name__)

# 与 config / file_manager 保持一致的默认值
_DEFAULT_STORAGE_NAME = "桌面文件收纳"


def _load_config_or_default():
    """
    读取配置；**读失败时记录 WARNING 并回退空配置**（空配置 → 默认桌面 / 默认存储根）。

    旧实现（AW-6 之前）在 `_storage_root()` 里 `except Exception: pass`，
    配置读不出来就**静默**改用默认路径——用户和开发者都不知道配置没读到（AW-8）。
    现在把这次失败记下来（WARNING 默认打到 stderr，跑脚本的人看得见）。

    ⚠️ 行为说明：分类清单是**配置驱动**的，读失败 → `category_folders({})` 为空 →
    恢复计划为空 → **一个文件都不会被移动**（fail-closed）。这比旧实现「读不到配置就
    硬编码 5 个默认分类照搬」更安全：读不出配置时，我们无法确定用户的分类目录布局，
    贸然搬文件的风险更大。抽成窄接口（依赖 `config.load_config`，可被 mock 注入）便于单测。
    """
    try:
        return config.load_config()
    except Exception as e:
        logger.warning(
            "读取配置失败（%s），改用默认路径；分类清单为空，不会移动任何文件", e
        )
        return {}


def resolve_desktop(cfg):
    """
    目标桌面目录：取 `config["desktop_path"]`；为空时回退 `~/Desktop`。

    ⚠️ 与 `file_manager.get_desktop_path` 的**缺省值相同**（都是 `~/Desktop`），
    但两者的**回退条件不同**：本函数只在 `desktop_path` 为空时回退；
    `get_desktop_path` 还会在「目录不存在」时也回退到 `~/Desktop`。
    本函数刻意**不**检查目录是否存在（fail-closed）：恢复目标以配置为准，宁可把文件
    恢复到一个尚未创建的目录名下，也不擅自改回 `~/Desktop` 而把文件搬到用户没指定的地方。
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
      ⚠️ 去重键是 `os.path.abspath(folder)`（AW-21）：旧实现按**原始字符串**去重，
      `shared` 与 `.\\shared` 这类**等价拼写**不会去重，计划里同一文件会出现两次
      （第二条报 `[WinError 2]`，不丢数据但计划不自洽）。
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
        key = os.path.abspath(folder)
        if key in seen:
            continue
        seen.add(key)
        label = name.strip() if isinstance(name, str) and name.strip() else folder
        result.append((label, folder))
    return result


def _category_dir(root, folder):
    """
    把分类目录名解析成 `root` 内的完整路径；越界返回 `None`（并记一条 WARNING 日志，
    **不静默**——`restore()` 是给人跑的脚本，静默跳过会让「某个分类被跳过」无从察觉）。

    两层校验：
    1. **词法校验**（abspath + commonpath）：挡住绝对路径、`..` 逃出 root，以及
       `con` / `aux` / `nul` / `D:evil` 这类会让 `commonpath` 抛 `ValueError` 的怪名字。
       旧脚本的目录名是写死的、天然安全；改成配置驱动后必须自己兜住这层，
       否则手工编辑的 `folder`（如 `..\\..\\evil`）会让脚本扫描存储根之外并把那里的文件搬回桌面。
    2. **realpath 复检**（AW-21，复用 `file_manager.realpath_escape_error`）：
       若 `root\\<folder>` 已存在且是指向根外的 junction / 符号链接，**词法校验会放行**、
       文件实际会被搬到存储根之外（复查已用 `mklink /J` 实测复现）。
    """
    root_abs = os.path.abspath(root)
    if os.path.isabs(folder):
        logger.warning("跳过分类目录 %r：不能是绝对路径", folder)
        return None
    target = os.path.abspath(os.path.join(root_abs, folder))
    try:
        # 用 commonpath 而不是 startswith（避免 `...\sub\stor` 这类前缀兄弟目录误判）
        if os.path.commonpath([target, root_abs]) != root_abs or target == root_abs:
            logger.warning("跳过分类目录 %r：越出了存储目录 %r", folder, root_abs)
            return None
    except ValueError:
        # 不同盘符（如 `D:evil`），或 Windows 保留设备名（如 `con`）经 abspath 变成
        # `\\.\con` —— 一律判越界。
        logger.warning("跳过分类目录 %r：与存储目录 %r 不在同一盘符（或名字非法）", folder, root_abs)
        return None
    # realpath 复检：挡住指向根外的 junction / 符号链接（AW-21）
    escape = file_manager.realpath_escape_error(root_abs, target)
    if escape:
        logger.warning("跳过分类目录 %r：%s", folder, escape)
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
    cfg = _load_config_or_default()
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
