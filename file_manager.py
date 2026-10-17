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
import time
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

# ── 文件稳定性判定（AW-7） ───────────────────────────────
#
# 文件监控（file_watcher）在归类前必须确认文件「已经写完」。watchdog 的
# created/modified 事件只说明「有写入发生」，而 500ms 防抖也挡不住仍在进行的大文件
# 复制：复制方每写一块都会刷新事件，但两次事件之间的空档足以让旧实现把**半个文件**
# 移走——复制方随后继续写的是那个已被移走的句柄，用户拿到的却是残缺副本。
# 判定方式：间隔采样 `os.path.getsize`，连续两次相同即认为写完。
DEFAULT_STABLE_INTERVAL = 0.5  # 两次采样之间的间隔（秒）
DEFAULT_STABLE_SAMPLES = 2     # 判定所需的采样次数（两个样本相等即稳定）

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


def is_stable(sizes, min_samples=DEFAULT_STABLE_SAMPLES):
    """
    **纯函数**：判断一串按时间顺序采样到的文件大小是否「稳定」（写完了）。

    规则（AW-7）：
    - 样本不足 `min_samples` → 不稳定（还没比过，不能冒险归类）；
    - **最后两个样本相等** → 稳定（大小不再变）；
    - 大小仍在变（最后两个不等）→ 不稳定。

    抽成纯函数（注入 `sizes` 序列、无副作用）是为了可单测：真实采样涉及
    sleep 与文件系统，无法在用例里稳定复现「正在复制」，但
    「`[100, 200]` → 不稳定 / `[100, 100]` → 稳定」这类判定逻辑可以精确断言。
    """
    if len(sizes) < min_samples:
        return False
    return sizes[-1] == sizes[-2]


def stable_files(paths, getsize=None, interval=DEFAULT_STABLE_INTERVAL,
                 sleep=time.sleep):
    """
    只读文件系统：对一批路径做「间隔采样大小、连续两次相同」的稳定性判定（AW-7）。

    返回 `(stable, unstable)`：已写完（可归类）的路径、仍在写入（应稍后重试）的路径。

    依赖全部可注入，便于单测（不真等、可模拟复制过程）：
    - `getsize`：取大小的接口，默认 `os.path.getsize`；
    - `sleep`：采样间隔的接口，默认 `time.sleep`（单测注入假 sleep 即可在「等待」
      期间改动真实临时文件，从而在真实文件系统上复现「正在复制」）；
    - `interval`：两次采样之间的间隔。

    ⚠️ 整批**共享一次等待**，而不是逐文件 sleep：本函数在 GUI 线程
    （`file_watcher._process_pending` 是 QTimer 槽）被调用，逐文件 sleep 会让
    一批 N 个文件卡住 `N × interval` 秒。

    ⚠️ 读不到大小的路径（已被删除 / 权限不足 / 采样途中消失）归入 `unstable`：
    宁可晚点再试，也不要在读不到大小时冒险搬走半成品。
    """
    if getsize is None:
        getsize = os.path.getsize

    first = {}
    for p in paths:
        try:
            first[p] = getsize(p)
        except OSError:
            pass  # 读不到 → 不进 second，最终归为 unstable

    if interval:
        sleep(interval)

    stable, unstable = [], []
    for p in paths:
        if p not in first:
            unstable.append(p)
            continue
        try:
            second = getsize(p)
        except OSError:
            unstable.append(p)
            continue
        (stable if is_stable([first[p], second]) else unstable).append(p)
    return stable, unstable


# 待归类文件本轮的处理动作（AW-7）。
ACTION_CATEGORIZE = "categorize"  # 已稳定 → 归类
ACTION_RETRY = "retry"            # 仍在写入 → 稍后重试
ACTION_GIVE_UP = "give_up"        # 重试太多次仍不稳定 → 放弃（留在桌面）


def stability_decision(stable, retries, max_retries):
    """
    **纯函数**：决定一个待归类文件本轮如何处理（AW-7 的重试策略）。

    - 已稳定 → `ACTION_CATEGORIZE`；
    - 不稳定且重试次数未达上限 → `ACTION_RETRY`（稍后重试）；
    - 不稳定且已达上限 → `ACTION_GIVE_UP`（**留在桌面**，绝不冒险搬走半成品；
      例如被持续写入的文件，用户可稍后手动拖入面板）。

    `retries` 是**已经**重试过的次数。抽成纯函数是为了让「重试上限」这条策略可单测
    ——它同时防住「搬走半成品」与「无限重试」两种坏结果。
    """
    if stable:
        return ACTION_CATEGORIZE
    if retries >= max_retries:
        return ACTION_GIVE_UP
    return ACTION_RETRY


# ── 安全取大小（AW-9） ───────────────────────────────────
#
# 界面在渲染文件列表/搜索结果时要对每个条目取 `os.path.getsize`。但从「列出目录」
# 到「逐条取大小」之间文件可能已被删除或移走（后台归类、用户手动操作、同步软件），
# 此时 `os.path.getsize` 抛 `OSError`，未捕获会让**整个列表/搜索渲染崩掉**。
# 取不到大小不是致命错误——显示一个占位符即可。
SIZE_PLACEHOLDER = "—"  # 取不到大小时显示的占位（em dash）


def safe_size(path, getsize=os.path.getsize):
    """
    **纯函数**：安全地取文件大小（字节）。

    取不到（文件已被删除/移走、权限不足、符号链接失效、路径是目录等）时，
    `getsize` 会抛 `OSError`（或其子类 `FileNotFoundError` / `PermissionError` /
    `NotADirectoryError` …）；本函数一律吞掉并返回占位符 `SIZE_PLACEHOLDER`，
    **绝不向上抛异常**——单个条目消失不应让整屏渲染崩溃。

    `getsize` 可注入，便于单测各种 `OSError` 子类（默认 `os.path.getsize`）。
    正常文件返回真实大小（int，单位字节）。
    """
    try:
        return getsize(path)
    except OSError:
        return SIZE_PLACEHOLDER


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

    ⚠️ **定位（AW-4 复查实测更正）：这是「纵深防御 + UX 改善」，不是在堵一个可达的
    数据丢失缺陷。** 早期勘察报告写的「把存储根父目录拖进来会把整个存储目录连同分类
    一起搬走 → 存储根位移、`config` 记录的路径全部失效」经**实测证伪**：关掉本校验后，
    把存储根 / 父 / 祖父 / 顶层祖先四级分别拖入分类，目标目录（`存储根\\分类\\...`）
    **必在被拖入目录之内**，`os.rename` 一律以 `WinError 5`（拒绝访问）失败，
    四级祖先全部返回 `(None, None)`，**存储根纹丝不动**。本校验的价值是给出
    **干净的静默拒绝**，而不是「尝试搬移 → 失败 → 记一条 ERROR 日志」。

    ⚠️ 不能用 `startswith` 判前缀：`...\\sub\\stor` 是 `...\\sub\\storage` 的字符串前缀，
    但它只是**兄弟目录**、并非祖先——`startswith` 会把它误判成祖先，从而拒绝一次
    完全正常的收纳。这里用 `os.path.commonpath`：`src` 是存储根的祖先 ⟺
    二者的公共路径**恰等于 src 本身**（`commonpath` 对不同盘符抛 `ValueError`，
    那种情况 src 不可能是祖先，返回 None）。

    ⚠️ **参数顺序是硬前提：必须写 `commonpath([src, root])`，src 在前。**
    本函数对大小写不敏感**不是显式意图**，而是依赖 `os.path.commonpath` 的实现细节：
    它内部先把各路径 `lower()` 再逐组件比较（故 `C:\\STORAGE` 与 `C:\\storage` 视为同一
    路径），**但返回值用 `paths[0]` 的原始大小写拼回**。于是「src 在前」时 `common == src`
    恒真；一旦顺序写反成 `[root, src]`，返回值带的是 **root** 的大小写，遇到大小写不同的
    输入时 `common == src` 失配 → **漏判祖先（放行）**。
    `tests/test_file_manager.py::TestMoveIntoCategoryRejectsStorageAncestors` 的
    `test_case_variant_*` 用例把这条顺序前提钉住了。

    ⚠️ **已知放行缺口（如实标注，不掩盖）**：`\\?\\C:\\storage` 这类**扩展长度前缀**路径
    经 `os.path.abspath` 后**保留 `\\?\\` 前缀**，`os.path.commonpath` 认盘符
    `\\?\\C:` ≠ `C:` → 抛 `ValueError` → 本函数**放行**（guard 被绕过）。
    但**实际不可利用**：分类目录必在被拖入源之内，随后真实 `os.rename` 会以 `WinError 5`
    失败，最终仍返回 `(None, None)`；且 `src` 来自 Qt 拖拽的 `QUrl.toLocalFile()`
    真实本地路径，资源管理器不会产生 `\\?\\`。用例
    `test_extended_prefix_is_known_passthrough_but_not_exploitable` 钉住这条已知行为。
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


def _normalize_ext(ext):
    """把扩展名归一化：转小写、去掉首尾空白与前导点。非字符串返回空串。"""
    if not isinstance(ext, str):
        return ""
    return ext.strip().lower().lstrip(".")


def extension_conflicts(categories, extensions, exclude=None):
    """
    **纯函数**：找出 `extensions` 与其它分类已声明的扩展名**重叠**的部分。

    返回 `[(扩展名, 冲突分类名), ...]`（按扩展名首次出现顺序、去重）；无重叠返回 `[]`。

    ⚠️ 为什么需要检测（AW-11）：`categorize_file` 遍历 `config["categories"]`
    并**取首个匹配**的分类，所以同一个扩展名被两个分类声明时，文件会路由到
    **由分类顺序决定**的不确定分类（`init_folders` 的首次整理同理：先遍历到的分类
    先把桌面文件搬走）。这是配置歧义，**不是设计特性**——默认分类之间没有任何重叠，
    也没有任何「优先级」机制，所以「首个匹配」只是循环的自然写法，而非有意的优先规则。

    - `exclude`：要排除的分类（**编辑**某个分类时传它自己）。按**对象身份**排除，
      而不是按名字——编辑时分类名可能在同一操作里被改掉，按名字会排除错。
    """
    exclude_id = id(exclude) if exclude is not None else None

    wanted = []
    seen = set()
    for e in extensions or []:
        n = _normalize_ext(e)
        if n and n not in seen:
            seen.add(n)
            wanted.append(n)
    if not wanted:
        return []

    conflicts = []
    for n in wanted:
        for cat in categories or []:
            if exclude_id is not None and id(cat) == exclude_id:
                continue
            if not isinstance(cat, dict):
                continue
            cat_exts = set()
            for e in cat.get("extensions") or []:
                en = _normalize_ext(e)
                if en:
                    cat_exts.add(en)
            if n in cat_exts:
                # 每个扩展名只报**首个**声明它的分类（与 categorize_file 的首个匹配一致）
                conflicts.append((n, cat.get("name", "?")))
                break
    return conflicts


def extension_conflict_error(categories, extensions, exclude=None):
    """
    纯函数：把扩展名重叠翻译成一句**用户可见**的中文提示（无冲突则返回 None）。

    供 GUI 在新建/编辑分类**保存前**调用：有冲突就拦截保存（与 AW-3 的
    `category_folder_error` 同样的「校验 → 提示 → 阻止」模式），避免产生
    「同一扩展名归到哪个分类由分类顺序决定」的歧义配置。
    """
    conflicts = extension_conflicts(categories, extensions, exclude=exclude)
    if not conflicts:
        return None
    parts = "、".join(f"{ext}（{cat}）" for ext, cat in conflicts)
    return f"扩展名与已有分类重叠：{parts}。请先修改扩展名，或编辑相关分类。"


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
    ⚠️ 列目录失败（目录被删/权限不足/采样途中消失）同样返回 `[]`，但**记 WARNING 日志**
    （AW-8）：返回值不变以免调用方崩，但「这个分类读不出来」这件事不能再无声无息。
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
    except OSError as e:
        # 返回 [] 保持公开契约（GUI 不能崩），但把失败原因记下来（AW-8）。
        logger.warning("列出分类目录失败，返回空列表：%s（原因：%s）", folder, e)
        return []

    # 按修改时间降序（最新的在前）
    files.sort(key=lambda x: x[2], reverse=True)
    return files


def _move_matching_files(source_dir, target_dir, extensions):
    """
    将源目录中匹配扩展名的文件移动到目标目录。

    返回 MoveStats(moved, failed, errors)：搬移失败不再被静默吞掉——
    既**返回**失败计数与原因（AW-2 的成果，保持不变），也**记录** WARNING 日志（AW-8），
    这样无论调用方是否检查返回值，失败都不会无声无息（与归类/拖拽路径的
    `_log_move_failure` 保持一致）。
    """
    moved = 0
    errors = []

    try:
        entries = os.listdir(source_dir)
    except OSError as e:
        # 连源目录都列不出来 → 这是一次**失败**，不是「0 个文件」。
        # 旧写法返回 failed=0 却带着非空 errors，只看失败计数的调用方会把它漏掉。
        logger.warning("列出待整理目录失败：%s（原因：%s）", source_dir, e)
        return MoveStats(0, 1, [e])

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
                # 失败必须留下痕迹（含半成品残留路径），别让「首次整理」的失败消失。
                _log_move_failure("首次整理", full, result.error)

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
    # ⚠️ 这是**纵深防御 + UX 改善**，不是在堵一个可达的数据丢失缺陷：把存储根的父目录
    # （如 Documents）拖进来时，目标目录（`存储根\分类\...`）必在源之内，`os.rename`
    # 会以 WinError 5 失败——即使没有本校验，存储根也纹丝不动（AW-4 复查实测**证伪**了
    # 旧描述「存储根位移、配置全部失效」）。本校验让这种情况变成**干净的静默拒绝**，
    # 而不是「尝试搬移 → 失败 → 记一条 ERROR 日志」。
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


# ── 回收站删除（Windows Shell FileOperation） ─────────────
#
# `SHFileOperationW` 的 `fFlags` 是 `FOF_*` 位掩码。旧实现（dashboard.py）
# 错把 `SHEmptyRecycleBin` 的 `SHERB_*` 常量（NOCONFIRMATION=0x1 /
# NOPROGRESSUI=0x2 / NOSOUND=0x4）当成 `FOF_*` 用，于是真正想要的
# `FOF_NOCONFIRMATION`(0x10) 根本没被设上 → 系统照旧弹确认框。
# 这里改用正确的 `FOF_*` 常量，并把「标志位」与「结果判定」抽成纯函数，
# 以便在不调用真实 `SHFileOperation`（会真删文件）的前提下单测。

FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


def build_delete_flags():
    """
    纯函数：`SHFileOperationW(FO_DELETE)` 要用的 `fFlags`。

    - `FOF_ALLOWUNDO`：删除进**回收站**（可撤销），而不是永久删除；
    - `FOF_NOCONFIRMATION`：不弹「确实要删除吗」确认框；
    - `FOF_NOERRORUI`：出错不弹系统错误框（由调用方自己处理并提示用户）；
    - `FOF_SILENT`：不显示进度对话框。

    ⚠️ 回归点：旧代码错把 `SHEmptyRecycleBin` 的 `SHERB_*`（0x1/0x2/0x4）
    当成 `FOF_*` 用，**漏掉了 `FOF_NOCONFIRMATION`(0x10)**，于是确认框照弹。
    本函数保证 0x10 一定在里面（见 tests/test_file_manager.py）。
    """
    return FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT


def interpret_delete_result(result, aborted):
    """
    纯函数：把 `SHFileOperationW` 的返回值与 `fAnyOperationsAborted` 翻译成
    「这次删除**真的成功了**吗」（True / False）。

    - `result`：API 返回值，0 表示函数层面没有报错；
    - `aborted`：`SHFILEOPSTRUCTW.fAnyOperationsAborted`，**用户在确认框上点了
      「取消」**时为真（ctypes 的 `BOOL` 就是 `c_int`，非 0 即真）。

    ⚠️ 回归点：只看 `result == 0` 是不够的——用户点「取消」时 `SHFileOperationW`
    仍返回 0，但**文件一个都没删**。旧代码据此把「取消」也算成删除成功
    （界面显示删了、实际没删）。所以必须同时要求 `not aborted`。
    """
    return result == 0 and not aborted


# ── 桌面图标排列 ─────────────────────────────────────────

def should_arrange_icons(config):
    """
    **纯函数**：根据配置决定启动时是否自动重排桌面图标（AW-13）。

    旧行为（AW-13 之前）是**每次启动无条件**发 `LVM_ARRANGE/LVA_SNAPTOGRID`
    重排用户的桌面图标，用户无法关闭。现在加一个配置项 `arrange_icons` 允许关闭，
    但**默认值保持 True**——不改变现有用户的行为（默认值属产品决策，见 AUTOWORK
    「待确认」区；改成默认 False 会让所有老用户突然不再排列）。

    向后兼容：老配置里**没有这个键** → 返回 True（仍然排列），与旧行为一致。
    配置层 `config.load_config` 也会在补全缺失字段时把它填成 True
    （见 `config.DEFAULT_CONFIG`），所以无论从哪一层看，缺省都是「排列」。
    只有**显式**把 `arrange_icons` 设成假值（JSON `false`）才关闭。

    抽成纯函数是为了可单测（GUI 入口 `main.py` 不 import，只做 py_compile）。
    """
    return bool(config.get("arrange_icons", True))


def _arrange_desktop_icons_impl():
    """
    实际执行桌面图标排列（对齐网格）：找到桌面的 `SysListView32` 并发 `LVM_ARRANGE`。

    返回 True 表示已发出排列消息；False 表示没找到目标窗口（如 Win+D / 幻灯片壁纸
    等情况下连顶层枚举也没找到）。

    ⚠️ 本函数**不吞异常**——任何异常都向上抛，由 `arrange_desktop_icons` 统一记录。
    把 ctypes 那一段抽成这个窄接口（可被 mock 注入），是为了让「排列失败」这条路径
    **可单测**：旧实现把整段包在 `except Exception: pass` 里，测试根本够不到。
    """
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
    return False


def arrange_desktop_icons():
    """
    自动排列桌面图标（对齐网格）。best-effort，**失败返回 False**。

    与旧实现的唯一区别（AW-8）：失败不再 `except Exception: pass` **静默**吞掉——
    记一条 WARNING 日志（默认打到 stderr，用户/开发者看得见）后再返回 False。
    返回值仍是布尔，调用方（`main.py`）的行为不变（排列只是锦上添花，失败不该拦启动）。
    """
    try:
        return _arrange_desktop_icons_impl()
    except Exception as e:
        logger.warning("自动排列桌面图标失败（已忽略，不影响启动）：%s", e)
        return False
