"""
文件管理模块 — 文件分类、移动、列出。

⚠️ 平台前提（no-clobber 保证的基础）：
本模块「绝不覆盖已存在的同名目标」这套保证，隐含依赖 **Windows 的 `os.rename`
语义**——对已存在的文件或目录**一律**抛 `FileExistsError`，从不替换。
而 POSIX 的 `os.rename` 语义不同：它会**静默替换**已存在的**文件**和**空目录**；
只有目标是非空目录时才抛 `ENOTEMPTY`（此时不替换，与 Windows 一样安全）。
也就是说 POSIX 下**文件**目标会被静默覆盖，**真的会丢数据**；而**空目录**被替换
只是破坏了 no-clobber 保证（空目录里没有数据可丢，不会丢文件）。
本项目是 Windows 专用（大量 `ctypes.windll` 调用），故当前是安全的；
但**移植到 POSIX 之前必须先改**这里（见 `_move_dir_no_clobber`），否则会踩。
"""
import errno
import logging
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

# 一批搬移的统计（成功数 / 失败数 / 失败原因列表 / 因配置非法被跳过的分类数），
# 供 init_folders 汇总上报。`skipped` 默认 0，旧的三元组构造调用无需改动。
MoveStats = namedtuple(
    "MoveStats", ["moved", "failed", "errors", "skipped"], defaults=(0,)
)

# 竞态下换名重试上限：_resolve_conflict 已保证正常情况不冲突，
# 这里只兜底「解析出目标名之后、原子占用之前被别的进程抢占」的极窄窗口。
_CONFLICT_RETRIES = 100

# 本模块的日志器。搬移失败（尤其是留下半成品残留）必须让用户/开发者看得见，
# 不能再像旧实现那样 `return None, None` 把 `.residual` 静默吞掉。
logger = logging.getLogger(__name__)


def _log_move_failure(action, src, error):
    """
    把一次失败的搬移记录到日志（含半成品残留路径）。

    `_move_no_clobber` 失败时会返回结构化结果，其中 error 若为 `PartialMoveError`
    还带着 `.residual`（没清干净的半成品路径）。调用方只看 `result.ok` 的话，
    「有个半成品要手工清」这件事就消失了——本函数专门负责把它喊出来。
    """
    residual = getattr(error, "residual", None)
    if residual is not None:
        logger.warning(
            "%s失败，源保留原处：%s（原因：%s）；半成品残留需手工清理：%s",
            action, src, error, residual,
        )
    else:
        logger.warning("%s失败，源保留原处：%s（原因：%s）", action, src, error)


def did_move(result):
    """
    判断 `categorize_file` / `move_into_category` 的返回值是否代表**真的移动了**。

    这两个函数的公开契约是 2 元组：成功返回 `(name, dest)`，失败返回 `(None, None)`。
    ⚠️ 陷阱：`(None, None)` 是**非空元组，在布尔语境里恒为真**，所以绝不能写
    `if move_into_category(...):`——那会把**失败也当成成功**（UI 显示已收纳、
    实际文件没动）。本函数判的是返回值里的 dest 是否为 None，而不是判元组本身。

    供调用方（含 GUI 拖拽路径）使用；本函数是纯函数，便于单测。
    """
    return result is not None and result[1] is not None


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


class UnsafeCategoryFolder(ValueError):
    """
    分类的 `folder` 字段不安全（会逃出存储根目录），拒绝使用。

    继承 `ValueError`，便于调用方按「配置错误」统一处理。之所以**抛异常**而不是
    返回 `None` 或悄悄改用别的目录：静默兜底会把「配置有问题」这件事藏起来，
    继续把用户的文件搬到错误位置——这比直接报错危险得多。
    """


def category_folder_error(storage_root, folder_name):
    """
    纯函数：校验分类的 `folder` 字段是否会逃出存储根目录。

    返回 `None` 表示安全；否则返回一句中文错误说明（GUI 可直接展示给用户）。

    `folder` 字段来自用户自由文本（新建分类时填的「子文件夹名」），
    直接 `os.path.join(storage_root, folder)` 时：
    - `..\\..\\evil` 会解析到存储根之外；
    - 绝对路径（`C:\\Windows\\...` / `/etc`）会让 `join` **丢掉**存储根；
    两者都会把用户的桌面文件移出存储根目录。

    校验规则（在**任何平台**上行为一致——`\\` 与 `/` 都当分隔符，
    所以 `..\\..\\evil` 这种 Windows 写法在 POSIX 上也会被拒绝）：
    1. 非空；
    2. 不是绝对路径（不以分隔符开头、无盘符）；
    3. 不含任何 `..` 上级目录组件；
    4. 兜底用 `os.path.commonpath` 再确认解析后的路径确实落在存储根**内部**
       （严格子路径，等于存储根本身也算越界）。
    """
    if folder_name is None:
        return "子文件夹名不能为空。"
    if not isinstance(folder_name, str):
        # 非字符串（如手工编辑 JSON 写成 "folder": 123）统一按不安全处理，
        # 这样 category_folder_error 与 get_category_folder 的行为一致——
        # 后者不会再去 os.path.join 一个非字符串而抛 TypeError（那是另一种错误类型）。
        return "子文件夹名必须是文本。"
    name = folder_name.strip()
    if not name:
        return "子文件夹名不能为空。"

    # 绝对路径（以分隔符开头，或带盘符）→ 拒绝
    if os.path.isabs(name) or name[0] in ("/", "\\"):
        return "子文件夹名不能是绝对路径。"

    # 含「..」上级目录引用 → 拒绝（哪怕它恰好又绕回存储根内也不放行，
    # 这种写法只可能是有意为之，没有正当用途）
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts:
        return "子文件夹名不能包含「..」上级目录引用。"

    # 兜底：用 commonpath 再确认解析结果严格落在存储根内部
    try:
        root = os.path.abspath(storage_root)
        target = os.path.abspath(os.path.join(root, name))
        common = os.path.commonpath([root, target])
    except ValueError:
        # 不同盘符 / 无法比较 → 一定越界
        return "子文件夹名越出了存储目录。"
    if common != root or target == root:
        return "子文件夹名越出了存储目录。"

    return None


def realpath_escape_error(storage_root, target):
    """
    只读文件系统的判定函数：复检 `os.path.realpath`，判断 `target` 是否因
    **已存在的 junction / 符号链接**而解析到存储根之外。返回 None 或错误说明。

    ⚠️ 为什么需要这一步（AW-19）：`category_folder_error` 是**纯词法**校验，
    它只看字符串。若 `storage_root\\<folder>` 已经被替换成一个指向存储根之外的
    junction（Windows 上 `mklink /J` 不需要管理员权限）或符号链接，
    词法校验会**放行**，而文件实际会被写到存储根之外。复查已用 `mklink /J` 实测复现。

    修法选择：**做 realpath 复检并拒绝落在根外的**（而不是把它记录成已知残留风险）。
    理由：本程序的核心安全承诺是「用户的桌面文件只会在存储根内被搬动」；junction 会
    悄悄打破这条承诺（同步软件或恶意程序都能植入），且本项已经让「拒绝」变成
    **可见的降级**（应用照常启动、该分类被跳过并记日志），拒绝的代价很低。
    真正需要把分类放到别的盘的用户应当改 `storage_path`，而不是链单个分类目录。

    对**不存在**的路径，`realpath` 只解析已存在的前缀，因此新分类（目录尚未创建）
    不会被误拒；只有「目标已存在且解析到根外」才会被判越界。
    """
    try:
        real_root = os.path.realpath(storage_root)
        real_target = os.path.realpath(target)
        common = os.path.commonpath([real_root, real_target])
    except ValueError:
        # 不同盘符 / 无法比较 → 一定越界
        return "目录解析到了存储目录之外。"
    if common != real_root or real_target == real_root:
        return "目录解析到了存储目录之外。"
    return None


def storage_ancestor_error(storage_root, src_path):
    """
    纯函数：判断 `src_path` 是否为存储根目录**本身或其任一祖先目录**。
    返回 None 表示「不是」（可以移入分类）；否则返回一句中文错误说明。

    ⚠️ 这是**源路径**的校验（拖进来的东西），与 `category_folder_error` /
    `realpath_escape_error` 那两个**目标路径**校验不是一回事，别混用。

    ⚠️ 为什么必须拒绝（AW-4）：`move_into_category` 的旧防护只拒绝「分类文件夹本身」
    和「存储根这一层」。把存储根的**父目录**（如 `Documents`、`~`）拖进面板时，
    `_move_no_clobber` 会把**整个存储目录连同所有分类**搬进某个分类里，
    导致存储根位移、`config` 里记录的路径全部失效、用户的文件"消失"在错误位置。
    所以必须拒绝存储根**及其所有祖先**。

    ⚠️ 不能用 `startswith` 判前缀：`...\\sub\\stor` 是 `...\\sub\\storage` 的字符串前缀，
    但它只是**兄弟目录**、并非祖先——`startswith` 会把它误判成祖先，从而拒绝一次
    完全正常的收纳。这里用 `os.path.commonpath`：`src` 是存储根的祖先 ⟺
    二者的公共路径**恰等于 src 本身**（`commonpath` 对不同盘符抛 `ValueError`，
    那种情况 src 不可能是祖先，返回 None）。
    """
    try:
        root = os.path.abspath(storage_root)
        src = os.path.abspath(src_path)
        common = os.path.commonpath([src, root])
    except ValueError:
        # 不同盘符 / 无法比较 → src 不可能是存储根的祖先
        return None
    if common == src:
        return f"不能把存储目录「{root}」或其上级目录移入分类。"
    return None


def unsafe_category_message(category, error):
    """
    纯函数：为被跳过的非法分类生成一句**用户可见**的中文提示。

    抽成纯函数是为了可单测（GUI 侧只负责把它展示出来，不重复拼接文案）。
    """
    name = category.get("name", "?") if isinstance(category, dict) else category
    return f"分类「{name}」的目录名不安全，已跳过：{error}"


def get_category_folder(config, category):
    """
    获取分类对应的子文件夹完整路径（位于存储根目录下，而非桌面）。

    ⚠️ 安全：`folder` 字段来自用户自由文本，可能越界（`..\\..\\evil`、绝对路径等），
    因此这里做越界校验：越界则抛 `UnsafeCategoryFolder`，**绝不静默兜底**到别处。
    校验分两步：先做纯词法校验（`category_folder_error`），再对最终目标做
    `realpath` 复检（`realpath_escape_error`），挡住 junction / 符号链接逃逸。

    ⚠️ 本函数**会抛异常**。除本模块内部已改为「捕获并降级」的四个调用点外，
    其它调用点（尤其是 GUI）应改用 `safe_category_folder`，不要让坏配置崩掉整个 App。
    """
    folder_name = category.get("folder", category["name"])
    root = get_storage_root(config)
    error = category_folder_error(root, folder_name)
    if error:
        raise UnsafeCategoryFolder(
            f"分类「{category.get('name', folder_name)}」的子文件夹名不安全："
            f"{folder_name!r}（{error}）"
        )
    target = os.path.join(root, folder_name)
    escape = realpath_escape_error(root, target)
    if escape:
        raise UnsafeCategoryFolder(
            f"分类「{category.get('name', folder_name)}」的目录名不安全："
            f"{target!r}（{escape}）"
        )
    return target


def safe_category_folder(config, category):
    """
    同 `get_category_folder`，但**绝不抛 `UnsafeCategoryFolder`**。

    坏配置（folder 越界，或 `storage_root\\<folder>` 是指向根外的 junction/符号链接）时，
    记一条 ERROR 日志并返回 `None`，调用点据此**跳过该分类**。

    这就是 AW-19 要的「可见的降级」：坏配置下应用照常启动、其余分类照常工作，
    用户能在日志里看到「某个分类的目录名不安全，已跳过」，而不是整个 App 崩掉
    （旧行为：`init_folders` 未捕获 → 启动即崩；`categorize_file` 在 QTimer 槽里
    抛出 → abort 事件循环；`get_files_in_category` / `move_into_category` → GUI 崩）。
    """
    try:
        return get_category_folder(config, category)
    except UnsafeCategoryFolder as e:
        logger.error("%s", unsafe_category_message(category, e))
        return None


def init_folders(config):
    """
    初始化分类文件夹：
    1. 确保所有分类子文件夹存在（每次启动都执行）
    2. 仅首次运行时把桌面上已有的匹配文件移入对应文件夹
       （用 config 里的 initialized 标记，避免每次启动都静默移动文件）

    返回 MoveStats(moved, failed, errors, skipped)：首次运行搬移的统计。
    搬移失败不再被静默吞掉，调用方可以据此提示用户。

    ⚠️ 坏配置（某分类的 folder 越界）不再让本函数抛异常：该分类被**跳过**
    （计入 `skipped`）并记 ERROR 日志，其余分类照常初始化——
    这样 `main.py:101` 的启动路径不会因为一个非法 `folder` 而整个崩掉。
    """
    desktop = get_desktop_path(config)
    first_run = not config.get("initialized", False)

    moved = 0
    failed = 0
    errors = []
    skipped = 0

    for cat in config["categories"]:
        folder = safe_category_folder(config, cat)
        if folder is None:
            # 该分类配置非法 → 跳过它，其余分类照常工作（可见的降级）。
            skipped += 1
            continue
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

    return MoveStats(moved, failed, errors, skipped)


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
            folder = safe_category_folder(config, cat)
            if folder is None:
                # 匹配到的分类配置非法 → 跳过它继续找别的安全分类，
                # 绝不让 QTimer 槽（file_watcher.py:78）因坏配置抛出而 abort 事件循环。
                continue
            os.makedirs(folder, exist_ok=True)

            result = _move_no_clobber(file_path, folder, os.path.basename(file_path))
            if result.ok:
                return cat["name"], result.path
            # 失败不再静默吞掉：至少写进日志，别让 `.residual`（半成品路径）消失。
            # 公开 API 仍是 2 元组 (None, None)，file_watcher 的解包契约不变。
            _log_move_failure("归类", file_path, result.error)
            return None, None

    return None, None


def get_files_in_category(config, category):
    """
    列出分类文件夹中的顶层条目（文件 + 子文件夹），按修改时间降序排列。
    返回 [(full_path, name, mtime_datetime), ...]。子文件夹用 isdir 判断。

    ⚠️ 坏配置（分类 folder 越界）不再抛异常：返回 `[]` 并记 ERROR 日志，
    这样 GUI 刷新（dashboard/desktop_panel）不会因一个非法分类而整屏崩掉。
    """
    folder = safe_category_folder(config, category)
    if folder is None:
        return []
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

    ⚠️ 坏配置（分类 folder 越界）不再抛异常：返回 (None, None) 并记 ERROR 日志，
    这样拖拽路径（dashboard/desktop_panel）不会因一个非法分类而崩。
    """
    if not os.path.exists(src_path):
        return None, None

    folder = safe_category_folder(config, category)
    if folder is None:
        return None, None
    src_abs = os.path.abspath(src_path)
    folder_abs = os.path.abspath(folder)

    # 已在目标分类内 → 跳过
    try:
        if os.path.commonpath([src_abs, folder_abs]) == folder_abs:
            return None, None
    except ValueError:
        pass  # 不同盘符，不在此判断

    # 源是分类文件夹 → 拒绝（非法分类直接跳过，不参与比较）
    cat_folders = set()
    for c in config.get("categories", []):
        f = safe_category_folder(config, c)
        if f is not None:
            cat_folders.add(os.path.abspath(f))
    if src_abs in cat_folders:
        return None, None

    # 源是存储根**或其任一祖先目录** → 拒绝（AW-4）。
    # 旧防护只挡「存储根这一层」，把存储根的父目录（如 Documents）拖进来会把
    # 整个存储目录连同分类一起搬走 → 存储根位移、配置全部失效。
    if storage_ancestor_error(get_storage_root(config), src_abs):
        return None, None

    os.makedirs(folder, exist_ok=True)
    result = _move_no_clobber(src_path, folder, os.path.basename(src_path))
    if result.ok:
        return os.path.basename(result.path), result.path
    # 拖拽路径同样不能再吞掉失败原因（含 `.residual` 半成品路径）。
    _log_move_failure("拖拽收纳", src_path, result.error)
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


class PartialMoveError(OSError):
    """
    搬移失败，且失败时留下的半成品（空占位 / 半拷贝目录）**没能清干净**。

    正常情况下失败会被清理掉、不留垃圾；只有当清理本身也失败时（例如文件
    被别的进程锁住）才抛这个错误。残留路径见 `.residual`，调用方可据此提示
    用户「有个半成品要手工清」，而不是让垃圾悄悄躺在存储目录里。
    """

    def __init__(self, cause, residual):
        super().__init__(f"搬移失败且半成品未清干净：{residual}（原因：{cause}）")
        self.cause = cause
        self.residual = residual


def _cleanup_partial(dest, is_dir):
    """
    清掉失败搬移留下的半成品。返回清理后**仍残留**的路径（清干净则返回 None）。

    - 文件：占位是用 `O_CREAT|O_EXCL` 独占创建的，**一定是我们自己的**，
      所以无条件删除——哪怕跨盘 `copy2` 已经写进部分内容（非空），
      也不能留下半截垃圾（旧实现只在大小为 0 时才删，非空残留会漏网）。
    - 目录：跨盘 `copytree` 中途失败留下的半拷贝树（源目录完好无损），
      整个删除。⚠️ 只在**确认目标目录是我们自己创建的**时候才调用本函数：
      所有权证据来自 `_move_dir_no_clobber` 里我们自己的 `os.makedirs(dest)`
      （`exist_ok=False`）——它先原子占用目标名，成功即证明 dest 是本轮的；
      随后 `copytree(..., dirs_exist_ok=True)` 才往里拷。目标已存在时
      `makedirs` 抛 `FileExistsError`，那目录不是我们的，**绝不清**。
    """
    try:
        if is_dir:
            shutil.rmtree(dest, ignore_errors=True)
        else:
            os.remove(dest)
    except OSError:
        pass
    return dest if os.path.exists(dest) else None


def _move_file_no_clobber(src, dest):
    """
    文件：先用 O_CREAT|O_EXCL 原子占位，再搬入占位处。
    目标已被别人占用时抛 FileExistsError（交由上层换名重试），
    因此绝不可能覆盖已存在的同名文件——这正是原来「先查存在再 move」
    之间那条竞态窗口会造成的数据丢失。

    O_EXCL 保证了这个占位**一定是本进程创建的**，所以失败时可以直接清掉它
    （跨盘 `copy2` 中途失败可能已写入部分内容，非空的半截同样要清）。
    """
    fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        shutil.move(src, dest)
    except BaseException as e:
        leftover = _cleanup_partial(dest, is_dir=False)
        if leftover is not None:
            raise PartialMoveError(e, leftover) from e
        raise


def _move_dir_no_clobber(src, dest):
    """
    目录：`os.rename` 原子且不覆盖。

    ⚠️ **平台前提**：`os.rename` 的「目标已存在则抛 FileExistsError、绝不替换」
    是 **Windows 语义**；POSIX 的 `os.rename` 会**静默替换**已存在的**空目录**
    （目标是非空目录时才抛 `ENOTEMPTY`、不替换），那样就会丢数据——
    移植到 POSIX 前必须改用其它原子占位手段。

    跨盘符（EXDEV）时退回 `copytree`。**关键：目标名由我们自己先原子占用**
    （`os.makedirs(dest)`，`exist_ok=False`），成功即拿到「dest 是本轮创建的」
    这条**所有权证据**；随后让 `copytree(..., dirs_exist_ok=True)` 往里拷。
    这样任何失败清理都只可能删到**我们自己刚建的**目录。

    ⚠️ 为什么不能无条件清理：旧实现把「dest 已存在」与「copytree 起步失败」
    混为一谈，失败时无条件 `rmtree(dest)`。但 `copytree` 的第一步是
    `os.scandir(src)`——若 `src` 在「rename 抛 EXDEV」与「copytree」之间被并发
    删除，copytree 会在创建 dest **之前**就失败，而此时 dest 可能已被别的进程/
    用户并发创建，无条件清理就会**删掉别人的目录**（AW-17 复查实测：用户数据被删）。
    现在只有 `os.makedirs(dest)` 成功（=dest 确是我们建的）之后的失败才清理。
    """
    try:
        os.rename(src, dest)
        return
    except FileExistsError:
        raise
    except OSError as e:
        if getattr(e, "errno", None) != errno.EXDEV:
            raise
    # 跨盘符：先由我们自己原子占用目标名。这一步成功 = 拿到 dest 的所有权证据。
    # 目标已存在 → FileExistsError（不是我们的，交给上层换名重试，**绝不清理**）；
    # 其它 OSError（如父目录不可写）同样直接上抛，此时 dest 没建出来，更不能清理。
    os.makedirs(dest)
    try:
        shutil.copytree(src, dest, dirs_exist_ok=True)
    except BaseException as e:
        # 走到这里说明 dest 确实是我们刚建的 → 清掉半拷贝残留是安全的（源目录完好）。
        leftover = _cleanup_partial(dest, is_dir=True)
        if leftover is not None:
            raise PartialMoveError(e, leftover) from e
        raise
    shutil.rmtree(src)


def _move_no_clobber(src, folder, filename):
    """
    把 src 移入 folder，自动消解重名冲突，返回 MoveResult(ok, path, error)。

    与旧的「_resolve_conflict 之后直接 shutil.move」不同：
    - 名字是**原子占用**的，杜绝 TOCTOU 竞态覆盖；
    - 任何失败都以结构化结果返回（含原因），绝不静默吞掉。

    ⚠️ 原子占用依赖平台语义：文件用 `O_CREAT|O_EXCL`（跨平台安全），
    目录用 `os.rename`（**Windows 语义才不覆盖**，见 `_move_dir_no_clobber`）。
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
