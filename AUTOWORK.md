# 自动作业单 · desktop-file-organizer

> 本文件是自动作业的**唯一状态来源**。每次被唤醒时，先读本文件，找到「当前进度」里
> 第一个未完成的条目，做完、验证、提交、推送、勾选，然后停止。不要顺手做下一项。

## 硬性规则

1. **分支**：所有工作只在 `autowork/2026-10-16` 分支上。**永远不要碰 `master`**，
   不要 `force push`，不要改远端设置，不要删远端分支。
2. **一次一项**：每轮只推进一个条目。做完就停。
3. **每项必提交并推送**：`git add` → `git commit -m "[AW-<编号>] <做了什么>"` →
   `git push`。**不 push 的话工作只停在本地，等于没做。**（代理已配好，
   见 `.git/config` 的 `http.proxy`，推送慢是正常的，别中断。）
4. **每项必验证**：改完必须跑测试。`AW-0` 建好之前，用一次性脚本验证并在条目里
   写清怎么验的；`AW-0` 之后，统一用 **`python -m unittest discover -s tests -v`**。
   - 用例数**只增不减**。以「当前进度」区最新一条记录的数量为准。
   - 修 bug 时若某个已有用例失败，先判断是**用例写错了**还是**代码退化了**，别直接改用例让它变绿。
   - **新增回归测试后，要临时撤掉修复验证它确实会变红**，再装回去。前后都绿的测试等于没写。
     ⚠️ 做「撤掉修复」验证时，**必须先确认回退本身生效了**（比如 `git diff` 看改动确实没了），
     否则得到的是假阳性——比不验证更糟。
5. **🔴 数据安全红线（最重要）**：这个程序会**真实地移动、删除用户的桌面文件**。
   - **绝不运行 `main.py`**——它会重排真实桌面图标（`arrange_desktop_icons`）并搬走真实文件。
   - **绝不运行 `restore_files.py`**——它会把分类目录里的真实文件搬回桌面。
   - **绝不**对真实 `~/Desktop`、真实 `~/Documents/桌面文件收纳` 或任何真实用户目录做写操作。
   - 所有涉及移动/删除/重命名的测试，**必须在 `tempfile.TemporaryDirectory()` 里造目录**，
     用 `unittest.mock.patch` 打桩 `get_desktop_path` / `get_storage_root`。
   - ⚠️ **`config.json` 地雷**：`init_folders` 会调 `save_config`，而 `config.py:13` 的
     `CONFIG_PATH` 在非打包状态下指向**仓库根目录**下的 `config.json`。任何测试只要碰到
     `init_folders` / `save_config`，**必须先 `mock.patch("config.CONFIG_PATH", <临时路径>)`**，
     否则会往仓库根目录写真实配置文件。**每次跑完测试后 `git status` 必须干净**——
     出现 `config.json` 就是踩了这颗雷，立刻清掉并补打桩。
   - 需要人工确认「程序能跑起来」的条目，只做**静态检查**（`python -m py_compile`）或
     在临时目录上跑，并在条目里写明**没有**在真实桌面上验证。
6. **同一项连续失败两次**就标记 `BLOCKED` 并写清原因，跳到下一项，不要死磕。
7. **不确定就跳过**：改默认分类、改磁盘目录名、改数据格式、动 UI 布局这类需要用户决策的，
   记到「待确认」区，**不要擅自决定**。
8. **队列空了就停**：不要自己编条目凑数。空转没有产出，只烧钱。
9. **本机环境**：Python 3.14.7，`PyQt5` + `watchdog` 已装，**没有 pytest**——
   用标准库 `unittest`，**不要引入新依赖**。`file_manager.py` / `config.py` 可在无 PyQt5 下
   import（只依赖 os/shutil/ctypes/json），GUI 模块（`dashboard.py` / `desktop_panel.py`）不要 import。
10. **仓库是浅克隆**（只有 2 个提交），历史不完整，别指望 `git log` 考古。

## 背景

这是一个 Windows 桌面文件自动整理工具（Python + PyQt5），把桌面文件按扩展名移入
`Documents\桌面文件收纳` 下的分类文件夹，并监控桌面自动归类。

**勘察结论（2026-10-16 人工审计，非猜测）**：
- 全仓**没有任何自动化测试、没有 CI、没有 lint 配置、没有 dry-run**，改动目前无法自动验证。
- 存在多处**可能丢失或错放用户文件**的路径，其中「首次启动静默搬走桌面文件」和
  「配置损坏导致二次搬移」最危险。
- 本作业单的顺序是刻意排的：**先建可验证性，再修数据安全问题，然后正确性，最后健壮性/打磨**。
  不要跳着做——后面每一项的验证都依赖 AW-0 建的测试基建。

## 已做过的对抗性复查（不要重复做，但要知道盲区）

**AW-0 的复查结论（2026-10-17 独立 agent，结论：够格）**：
- 36 个用例真绿、**真能抓回归**（4 种不同的逻辑破坏分别让 6 / 1 / 1 / 1 个用例变红）；
- **确实不碰真实目录**：插桩监控了 361 次写操作，落在真实家目录的 **0 次**；
- `master` 未动（仍 `9476d9d`），改动只限 `tests/`、`README.md`、`AUTOWORK.md`，无运行产物污染。

**⚠️ 必须知道的盲区（直接影响 AW-1/AW-2）**：
1. **`init_folders` / `_move_matching_files` 零覆盖**——这是**最高风险**的函数
   （会真实移动桌面文件，并调 `save_config` 往仓库根写 `config.json`）。
   当前仓库根没有 `config.json` **只是因为没测它**，不是因为测试挡住了它。
2. **`save_config` / `load_config` 零覆盖**——而 **AW-1 要改的正是这两个**。
   所以 AW-1 必须**先补测再改**（见 AW-1 条目里的前置要求）。
3. `get_files_in_category` 零覆盖。
4. 小瑕疵：`move_into_category` 的跨盘符 `ValueError` 分支未测；
   `test_result_is_inside_folder` / `test_other_desktop_files_untouched` 断言偏弱
   （只查存在性，没查内容）；`test_name_conflict_renames_on_move` 没像 categorize 版本
   那样校验原文件内容保留。**后续碰到这些函数时可以顺手补强**，但不要为了凑数而改。
5. 澄清一条：实现产物是**无空格**的 `name(1).ext`。如果哪个条目里写成了
   `name (1).ext`（带空格），那是描述笔误，**以代码行为为准**。

## 当前进度

- [x] **AW-0 建测试基建（可验证性）** —— 这是后面所有条目的前提，必须第一个做。
      建 `tests/` 目录，用标准库 `unittest`（零新依赖），入口
      `python -m unittest discover -s tests -v`。
      首批覆盖 `file_manager.py` 的纯逻辑：`get_desktop_path` / `get_storage_root` /
      `get_category_folder` / `_resolve_conflict` / `categorize_file` / `move_into_category`。
      **所有用例必须在 `tempfile.TemporaryDirectory()` 里造源目录和目标目录**，
      用 `unittest.mock.patch` 打桩配置里的路径——绝不碰真实桌面。
      顺手在 `README.md` 加一节「运行测试」，写清命令。
      完成标准：`python -m unittest discover -s tests -v` 全绿，用例数 ≥ 25，
      且**故意改坏一处逻辑能让对应用例变红**（验证测试真的有效，不是摆设）。
      验证后把实际用例数记到本条目末尾。
      ✅ 已完成（2026-10-16）：实际 **36** 个用例，`python -m unittest discover -s tests -v`
      全绿。反向验证：把 `_resolve_conflict` 的重命名模板从 `{name}({counter})` 改成
      `{name} ({counter})`（多一个空格），重跑得 **6 failed**；`git diff` 确认回退干净后
      重跑恢复全绿。全程在 `tempfile.TemporaryDirectory()` 内、config 指向临时路径，
      未触碰真实桌面，仓库根目录未生成 `config.json`。

- [x] **AW-1 修 `save_config` 非原子写 + `load_config` 静默回退（数据安全，最高优先级）**
      问题：`config.py:82-85` 直接 `open(...,'w')` 写入，写中断即产生半截 JSON；
      `config.py:71-79` 遇 `JSONDecodeError` 静默回退默认配置并**覆盖写回**，
      此时 `initialized` 变回 `False`，下次启动 `init_folders` 会**再次把整个桌面搬一遍**。
      ⚠️ **前置要求（AW-0 的对抗性复查发现的盲区，必须照做）**：AW-0 建的 36 个用例
      **没有覆盖 `save_config` / `load_config` / `init_folders` / `_move_matching_files` /
      `get_files_in_category`**——而这一项要改的**正是前两个**。所以：
      **先补 `save_config` / `load_config` 的用例（含「半截 JSON」「非法 JSON」
      「`initialized` 状态保留」这三条），确认它们当前是绿的（即在描述旧行为），
      再动手改代码。** 不这么做的话，「用例只增不减」这条规则在本次改动上是空的，
      等于没有回归网。改完后再把描述旧行为的用例改写成断言新行为，
      并补一条「配置损坏不会触发二次搬移」的端到端用例（用 `init_folders` +
      打桩 `CONFIG_PATH` 和 `storage_path`，全程在临时目录里）。
      修法：写入改为「写临时文件 → `os.replace` 原子替换」；解析失败时
      **先把损坏文件备份成 `config.json.corrupt-<时间戳>`**，再回退默认值，
      并且**保留原来的 `initialized` 状态**（从备份里尽量捞），不要让损坏触发二次搬移。
      新增用例：模拟半截 JSON / 非法 JSON，断言 (a) 备份文件存在且内容等于原损坏内容，
      (b) 不会因配置损坏而重新执行首次搬移。
      ✅ 已完成（2026-10-17）：实际 **52** 个用例（36 → 52，新增 `tests/test_config.py`
      共 16 条），`python -m unittest discover -s tests -v` 全绿。
      按要求先补 `save_config`/`load_config` 旧行为用例（半截 JSON / 非法 JSON /
      initialized 状态，共 10 条）确认在旧代码上为绿，再动代码；改完后改写成断言新行为。
      修法：`save_config` 走 `_atomic_write_json`（同目录临时文件 + `os.replace`）；
      `load_config` 解析失败时 `shutil.copyfile` 备份为 `config.json.corrupt-<时间戳>`，
      并用正则从原始文本抢救 `initialized`，捞不到才回退默认 `False`。
      反向验证：`git checkout -- config.py` 撤掉修复、`git diff` 确认回退生效后重跑，
      得 **5 failed**（原子写保护 1 + 损坏备份 2 + 保留 initialized 1 + 端到端二次搬移 1），
      装回修复后恢复 52 全绿。全程 `mock.patch("config.CONFIG_PATH", 临时路径)` +
      `tempfile.TemporaryDirectory()`，未在真实桌面验证，仓库根目录未生成 `config.json`。

- [x] **AW-2 修 `_resolve_conflict` 的 TOCTOU 与 `shutil.move` 静默失败（数据安全）**
      ⚠️ **前置要求（AW-0/AW-1 两次复查都点名的覆盖缺口，必须先补）**：
      **`init_folders` 的 `first_run=True` 分支（真正执行搬移的那条）仍零覆盖**、
      `_move_matching_files` 零覆盖、`get_files_in_category` 零覆盖。
      这一项要动的正是「移动失败怎么报」，而失败路径的宿主函数没测过。
      所以**先补这几个函数的用例（含「移动失败」路径），确认描述的是旧行为、是绿的，再改代码**。
      这几条不补，后面任何动 `init_folders` 的改动都是裸奔。
      问题：`file_manager.py:170-183` 先查存在再返回目标名，与随后的
      `shutil.move` 之间有竞态窗口；且 `file_manager.py:88-89` / `129-130` / `166-167`
      一律 `except: pass`，**移动失败用户完全看不到**。
      修法：冲突消解与移动都加异常处理，失败时**返回结构化结果（成功/失败 + 原因）**而不是静默 None；
      调用方（`init_folders` / `_move_matching_files`）据此统计失败数。
      新增用例：目标已存在同名文件 → 断言重命名到 `name (1).ext` 且原文件保留；
      模拟 `shutil.move` 抛 `OSError` → 断言返回失败结果而不是静默吞掉。
      ✅ 已完成（2026-10-17）：实际 **80** 个用例（52 → 80，新增 `tests/test_init_folders.py`
      共 28 条；另顺手把 `test_name_conflict_renames_on_move` 补强为校验原文件内容保留，
      不计数）。按要求**先补** `init_folders`(first_run) / `_move_matching_files` /
      `get_files_in_category` 的旧行为用例（含「移动失败」路径），确认在旧代码上为绿
      （52 → 72）再改代码；改完把其中 4 条旧行为断言改写为新行为。
      修法：
      - 新增 `_move_no_clobber(src, folder, filename)`：`_resolve_conflict` 降级为**只提议**
        一个当前不冲突的名字（保持纯函数，原 6 条用例不变），真正落盘前用
        `O_CREAT|O_EXCL`（文件）/ `os.rename`（目录，跨盘退回 `copytree`）**原子占用**目标名，
        被抢占则换名重试——彻底关掉「先查存在再 move」之间那条竞态窗口（旧代码在 Windows 上
        会经 shutil.move→copy2 静默覆盖被抢占的同名文件，造成数据丢失）。
      - 移动失败不再 `except: pass`，改为返回 `MoveResult(ok, path, error)`；
        `_move_matching_files` / `init_folders` 汇总为 `MoveStats(moved, failed, errors)`
        （旧行为：`init_folders` 恒返回 0、`_move_matching_files` 无返回值、失败静默）。
        公开 API `categorize_file` / `move_into_category` 的 `(name, dest)` / `(None, None)`
        契约保持不变（`file_watcher.py` 要按 2 元组解包）。
      反向验证（两步，回退前都先 `git diff` 确认生效）：
      (1) `cp` 备份后 `git checkout -- file_manager.py` 撤掉**整个**修复，`git diff --stat`
          确认 file_manager.py 已无改动、grep 不到 `_move_no_clobber` → 重跑得 **12 红**
          （11 个 ERROR 因辅助函数不存在 + 1 个 FAIL：`test_categorize_file_race_does_not_clobber`
          在**旧** `categorize_file` 上真的检出被覆盖）；
      (2) 只把 `_move_file_no_clobber` 的原子占位退回旧的直接 `shutil.move`（保留其余 API），
          `git diff` 确认后重跑 2 条竞态用例 → **2 failed**，断言输出正是 `'NEW' != 'RACER'`
          （抢跑者写入的文件被覆盖）。装回修复后恢复 80 全绿。
      全程 `tempfile.TemporaryDirectory()` + `mock.patch("config.CONFIG_PATH", 临时路径)`
      （`init_folders` 会调 `save_config`），未在真实桌面验证，仓库根目录未生成 `config.json`。

- [x] **AW-15 加固「配置损坏」的回退方向（AW-1 复查实测出的隐患，数据安全）**
      > 编号是后补的，但**位置在此处表示它比 AW-3 及之后的所有条目优先**。

      AW-1 的对抗性复查**实测**出两个隐患，AW-1 本身没覆盖：
      **(a) 回退方向是错的（真正的问题）**。`load_config` 解析失败时最终回退成
      `initialized=False`，而 `False` 的语义是「从没运行过」→ `init_folders` 会**二次搬移整个桌面**。
      但**配置文件存在**这件事本身就证明跑过一次。
      实测：把配置**截断在 `initialized` 之前**（这正是**旧的非原子写最可能产生的损坏形态**），
      正则抢救返回 `None` → 回退 `False` → **二次搬移确实发生了**。
      修法：**区分「文件不存在」和「文件存在但读不出来」**。只有前者才是首次运行；
      后者应保守地按「跑过」处理（不要触发首次搬移）。
      **这比正则抢救可靠得多——抢救应降级成「尽力而为的补充」，而不是主防线。**
      **(b) `_salvage_initialized` 会被无关的嵌套键骗到**。它用 `re.search` 取**第一个**匹配
      且**不分层级**。实测：
      - `{"nested": {"initialized": false}, "initialized": true, ...}` → 抢救出 **False**（**危险方向**）
      - `{"nested": {"initialized": true}, "initialized": false, ...}` → 抢救出 **True**
      修法：只扫**顶层键**（限定第一个 `{` 之后的深度 0）；若按 (a) 改完抢救不再必要，
      直接删掉它更好——**少一段会骗人的代码**。
      新增用例：截断在 `initialized` 之前的配置 → 断言**不二次搬移**；
      嵌套 `initialized` 在前/在后两种 → 断言不被骗；**配置文件不存在 → 断言仍按首次运行处理**
      （这条不能改坏，否则新装用户第一次跑就不搬文件了）；二进制/无法解码的配置 → 断言不二次搬移。
      ⚠️ 同时把 AW-0/AW-1 复查点名的覆盖缺口一并补上：
      **`init_folders` 的 `first_run=True` 分支**、`_move_matching_files`、`get_files_in_category`。
      （如果 AW-2 已经补过，这里只需确认并补漏。）
      ✅ 已完成（2026-10-17）：实际 **91** 个用例（80 → 91，净增 11 条，全在 `tests/test_config.py`），
      `python -m unittest discover -s tests -v` 全绿。两条一起做：
      - **(a) 回退方向改为保守**：`load_config` 现在只区分两种情形——
        「配置文件**不存在**」= 真首次运行（仍返回 `initialized=False`）；
        「文件**存在但读不出来**」（半截 JSON / 非法 JSON / 非 UTF-8 字节 / 读取 OSError /
        合法 JSON 但不是对象）→ 备份成 `config.json.corrupt-<时间戳>` 后回退默认值，但
        **强制 `initialized=True`**。理由：配置文件存在本身就证明程序跑过一次
        （首次运行时 `load_config` 会立刻把默认配置落盘），而 `False` 会让 `init_folders`
        再搬一次整个桌面；宁可少搬（用户可手动整理），也不能二次搬移。
      - **(b) 删掉 `_salvage_initialized`**（连同 `import re`）：它用 `re.search` 取第一个匹配
        且不分层级，会被无关的嵌套键骗到危险方向。按 (a) 改完后抢救不再必要，
        删掉比留着安全（加了一条 `hasattr` 用例钉住「这段会骗人的代码已删除」）。
      新增/改写用例（共 11 条）：截断在 `initialized` 之前 → 断言按「跑过」处理且**不二次搬移**；
      嵌套 `initialized` 在前/在后两种 → 断言不被骗（含端到端不二次搬移）；无法解码的二进制配置
      → 断言备份逐字节等于原内容且不二次搬移；读取 OSError（打桩 `builtins.open`）→ 按「跑过」；
      合法 JSON 但非对象（`[]`）→ 按损坏处理；损坏文本里写着 `initialized:false` → 仍按「跑过」；
      **配置文件不存在 → 断言仍按首次运行处理并真的搬移**（这条不能改坏，否则新装用户第一次跑
      就不搬文件了）。
      AW-0/AW-1 复查点名的覆盖缺口（`init_folders` 的 `first_run=True` 分支 /
      `_move_matching_files` / `get_files_in_category`）AW-2 已补齐，本轮确认无漏。
      反向验证：`cp` 备份后 `git checkout -- config.py` 撤掉修复，`git diff -- config.py`
      确认为空且 `grep _salvage_initialized` 命中旧函数（**回退已生效**）→ 重跑得 **11 failed**，
      其中 3 条端到端用例的断言输出正是「损坏配置不得再次搬移桌面文件」，即**二次搬移真的发生了**
      （在旧代码上实测复现，不是推断）；装回修复后恢复 91 全绿。
      全程 `mock.patch("config.CONFIG_PATH", 临时路径)` + `tempfile.TemporaryDirectory()`，
      未在真实桌面验证，仓库根目录未生成 `config.json`。

- [x] **AW-16 补跨盘分支的测试覆盖 + 清掉半拷贝残留（AW-2 复查实测，健壮性）**
      > 编号后补，位置在此 = 排在 AW-15 之后、AW-3 之前。

      AW-2 的对抗性复查**确认「TOCTOU 窗口已真的关掉」**：四种路径组合（文件/目录 × 同盘/跨盘）
      都实测过，含 C:→E: 真实跨盘、两线程并发、50 轮 × 4 线程压力测试，无一例覆盖或污染。
      我原本怀疑的「copytree 不原子」是**假警报**——`shutil.copytree` 内部第一步就是
      `os.makedirs(dst, exist_ok=False)`，本身就原子占用目标名。
      **但它带出三个次要却真实的问题**：
      1. **跨盘目录分支零测试覆盖**：`grep EXDEV|copytree|os.rename tests/` 无命中，
         所有目录用例都在同一个 tempdir（同盘），只走 `os.rename` 分支。
         也就是说**跨盘正确性完全靠 `shutil.copytree` 的实现细节兜底，没有任何回归保护**——
         将来 Python 改了 copytree 的行为，我们不会知道。
         修法：补一条用例，`mock.patch` 让 `os.rename` 抛 `OSError(EXDEV)`，
         断言走 copytree 分支且行为正确（目标已占时改名重试、不覆盖）。
      2. **半拷贝残留没有清理**：`copytree` 中途失败会留下一个**部分拷贝的 dest 目录**
         （对他人无覆盖、src 保留，但垃圾残留在存储目录里）；文件路径的跨盘 `copy2`
         中途失败同理可能残留非空占位文件。文件路径有 `_release_placeholder` 清理，
         **目录路径没有对应机制**。修法：目录分支也加失败清理，或至少把残留路径上报到
         `MoveResult`，让调用方能告诉用户「有个半成品目录要手工清」。
      3. **整套 no-clobber 保证隐含依赖 Windows 的 `os.rename` 语义**：
         本机（Python 3.14 / Windows）`os.rename` 对已存在的文件或目录**一律**
         `FileExistsError`，从不替换；而 POSIX 的 `os.rename` **会替换**。
         这个项目是 Windows 专用（大量 `ctypes.windll`），所以**不是 bug**，
         但**必须在代码注释里写明这个前提**，否则将来有人移植会踩。
      验证方式：新增的跨盘用例**撤掉修复后应变红**（先 `git diff` 确认回退生效）。
      ✅ 已完成（2026-10-17）：实际 **98** 个用例（91 → 98，净增 7 条，全在
      `tests/test_init_folders.py`：`TestCrossDriveDirectoryMove` 4 条 +
      `TestPartialMoveCleanup` 3 条），`python -m unittest discover -s tests -v` 全绿。
      - **(1) 跨盘目录分支覆盖**：新增 4 条，用 `mock.patch("file_manager.os.rename",
        side_effect=OSError(errno.EXDEV))` 强制走 `copytree`。含：同盘时**不**碰
        copytree 的对照组；跨盘搬移成功（`copytree` 确被调用、内容保留、源删除）；
        跨盘 + 目标已占 → 改名到 `proj(1)` 且旧目录内容不被覆盖/不嵌套；
        用 racy 桩逼 `copytree` 的 `makedirs` 撞上已占目标名（FileExistsError）
        → 换名重试、不覆盖。
      - **(2) 半拷贝残留清理**：把 `_release_placeholder`（只在大小为 0 时才删）换成
        `_cleanup_partial(dest, is_dir)` + 新增 `PartialMoveError`。文件占位由
        `O_CREAT|O_EXCL` 独占创建、**一定是自己的**，故失败时无条件删除
        （跨盘 `copy2` 已写入非空半截也能清）；目录分支 `copytree` 中途失败时
        删掉半拷贝树（`copytree` 的 FileExistsError 分支不清，那不是我们的）；
        清理本身也失败时抛 `PartialMoveError`，把**残留路径**放进 `.residual`
        上报给调用方（满足「至少上报」的要求）。
      - **(3) 写明平台前提**：模块 docstring + `_move_dir_no_clobber` +
        `_move_no_clobber` 三处注释写清「no-clobber 保证隐含依赖 Windows 的
        `os.rename` 语义（目标已存在一律 FileExistsError、从不替换），POSIX 会
        静默替换，移植前必改」。
      反向验证（两步，回退前都先 `git diff` 确认生效）：
      (1) `cp` 备份后 `git checkout -- file_manager.py` 撤掉**整个**修复，
      `git diff --stat` 确认 file_manager.py 已无改动、`grep PartialMoveError` 0 命中
      → 重跑得 **3 failed**（全是新增的 `TestPartialMoveCleanup`；4 条跨盘用例仍绿，
      因为该分支 AW-2 已实现，本轮只是补回归网）。
      (2) 装回修复后，只把 `_move_dir_no_clobber` 的 EXDEV 处理改回「直接 raise」
      （即废掉 copytree 分支），`git diff` 确认 `BREAK: EXDEV not handled` 已生效
      → 重跑得 **4 failed**，其中 **3 条正是 `TestCrossDriveDirectoryMove`** 的跨盘
      用例（证明它们真的在压 copytree 分支，不是摆设）。装回修复后恢复 98 全绿。
      全程 `tempfile.TemporaryDirectory()` + `mock.patch("config.CONFIG_PATH", 临时路径)`，
      未在真实桌面验证，仓库根目录未生成 `config.json`。

- [x] **AW-17 给 `_cleanup_partial` 加所有权校验 + 让拖拽路径上报 residual（AW-16 复查实测，数据安全）**

      AW-16 的对抗性复查确认「够格」（98 用例真绿、跨盘用例经**定点破坏**证明是判别性的、
      平台前提三处注释经实测准确、现实路径上无误删，并修好了旧实现「非空半截占位漏网」的真实缺陷），
      **但实测出一个窄而真实的误删洞**：
      `_move_dir_no_clobber` 的 `except BaseException` 分支**无条件 `rmtree(dest)`，
      不校验 dest 是不是自己创建的**。复合竞态下会删掉非自己创建的目录：
      (1) `os.rename` 抛 EXDEV（Windows 语义下意味着当时 dest 不存在）；
      (2) dest 在 rename 与 copytree 之间被并发创建；
      (3) src 在该窗口被删——此时真实 copytree 会在 `os.makedirs(dst)` **之前**的
      `os.scandir(src)` 就失败。
      复查**用真实 copytree 复现了用户数据被删**：
      `victim still a dir=False / USERDATA.txt content=DELETED`。
      概率极低，但代码层**没有任何所有权校验**——**不是假警报**。
      修法（复查建议，廉价）：把「dest 已存在」与「copytree 起步失败」两类失败**分开**，
      **只对「我们确实执行过 `makedirs` 之后」的失败做清理**——例如捕获 makedirs 成功的信号，
      或失败时先确认 dest 内是否含本轮临时标识。
      **关键：不能在无所有权证据时删目录。**
      新增用例：构造上述复合竞态（src 消失 + dest 预存用户目录）→
      断言**用户目录一字节没少**、且失败被如实上报。
      顺带修一条既有缺陷：`categorize_file`（`file_manager.py:114`）与
      `move_into_category`（`:208`）只看 `result.ok`，失败时 `return None, None`，
      于是 **`.residual` 在拖拽路径上被静默吞掉**（属既有调用方，非 AW-16 引入）。
      改成把 error 一并上报（至少写进日志），别让「有个半成品要手工清」这件事消失。
      另外 docstring 对 POSIX 的表述略宽（非空目录抛 ENOTEMPTY，只有文件和空目录才静默替换）
      ——顺手改准确。
      ✅ 已完成（2026-10-17）：实际 **102** 个用例（98 → 102，净增 4 条，全在
      `tests/test_init_folders.py`：`TestCleanupOwnership` 2 条 +
      `TestDragPathReportsFailure` 2 条），`python -m unittest discover -s tests -v` 全绿。
      - **(1) 失败清理加所有权校验（核心）**：`_move_dir_no_clobber` 的跨盘分支改为
        **先由自己 `os.makedirs(dest)`（`exist_ok=False`）原子占用目标名**，成功即拿到
        「dest 是本轮创建的」这条所有权证据；随后 `copytree(src, dest, dirs_exist_ok=True)`
        往里拷，**任何失败清理都只可能删到自己刚建的目录**。目标已存在 → `makedirs` 抛
        `FileExistsError`（不是我们的）→ 原样上抛交给上层换名重试，**绝不清理**。
        旧实现把「dest 已存在」与「copytree 起步失败」混为一谈、失败时无条件 `rmtree(dest)`：
        copytree 第一步是 `os.scandir(src)`，src 在该窗口被并发删除时 copytree 会在
        `makedirs` **之前**就失败，此时 dest 可能是别人/用户并发创建的目录 → 被误删。
      - **(2) 拖拽路径上报失败原因**：`categorize_file` / `move_into_category` 失败时
        不再只 `return None, None` 把 `result.error`（含 `PartialMoveError.residual`
        半成品路径）静默吞掉，新增模块级 `logger` + `_log_move_failure(action, src, error)`
        写进 WARNING 日志；公开 2 元组契约不变（`file_watcher` 的 `cat_name, new_path = ...`
        解包不受影响）。
      - **(3) docstring 改准确**：模块 docstring 与 `_move_dir_no_clobber` docstring 两处
        的 POSIX 表述改为「`os.rename` 静默替换**文件**和**空目录**，非空目录抛 `ENOTEMPTY`」。
      新增用例：
      - `test_compound_race_does_not_delete_foreign_dest`：**用真实 `copytree`** 构造复合竞态
        （mock `os.rename` 在抛 EXDEV 前并发创建 dest 用户目录 + 删除 src）→ 断言用户目录
        仍在、`USERDATA.txt` 内容 == `PRECIOUS`（一字节没少）、且失败被如实上报（`result.ok` False）。
      - `test_foreign_dest_not_deleted_when_copytree_fails_before_makedirs`：把解析逼到预存的
        用户目录上、copytree 在 `os.scandir` 就失败 → 断言预存目录不被删（更直接的所有权对照）。
      - `test_categorize_file_logs_move_failure` / `test_move_into_category_logs_residual`：
        用 `assertLogs("file_manager", level="WARNING")` 断言失败原因与 `.residual` 残留路径
        都出现在日志里，不再被吞掉。
      另把既有 2 条 `copytree` 模拟桩（`test_cross_drive_copytree_failure_leaves_no_partial_dir`、
      `test_leftover_is_reported_when_cleanup_fails`）里的 `os.makedirs(dst)` 改成
      `exist_ok=True`——因为 dest 现在由本函数先建好，这样才是对「copytree 拷到一半失败」的
      忠实模拟（语义未变，仍断言半拷贝残留被清干净）。
      反向验证（**定点**，未用 `git checkout origin/master -- file_manager.py` 那种超集回退）：
      只把 `_move_dir_no_clobber` 的跨盘分支改回旧的「无条件 `rmtree(dest)`」（去掉
      `os.makedirs(dest)` 所有权步骤、`copytree` 去掉 `dirs_exist_ok=True` 并恢复
      `except FileExistsError: raise`），`git diff` 确认 `BREAK` 标记已生效、`os.makedirs(dest)`
      只剩既有位置 → 重跑得 **2 failed**，正是两条新增的所有权用例，断言输出是
      `AssertionError: False is not true : 用户目录被误删了！`（即**用户目录真的被删掉了**，
      在旧行为上实测复现，不是推断）。装回修复后恢复 102 全绿。
      全程 `tempfile.TemporaryDirectory()` + `mock.patch("config.CONFIG_PATH", 临时路径)`，
      未在真实桌面验证，仓库根目录未生成 `config.json`。

- [x] **AW-18 修 `(None,None)` 被当成功 + 清掉 AW-17 留下的过时 docstring（正确性 + 打磨）**

      三件事，都来自 AW-17 的对抗性复查（该复查已确认 AW-17 够格、所有权声明真正闭合、
      且「新窗口」之说是假警报——新旧窗口边界与宽度相同，只是把 makedirs 从 copytree
      内部挪到了外面；真正被关掉的是那个更宽更易达的旧窗口）：
      1. **既有正确性 bug**：`dashboard.py:1324` 与 `desktop_panel.py:400` 写成
         `if p and move_into_category(...)`——而 `move_into_category` 失败时返回 `(None, None)`，
         **非空元组恒为真**，所以**失败也被当成成功**（UI 会显示移动成功，实际没动）。
         `categorize_file` 的调用方同理要查一遍。修法：判返回值而不是判元组本身
         （例如判 `result[1]` 是否为 None）。**别改公开契约**（仍是 2 元组）。
         新增用例：让移动失败 → 断言调用方**不**把这次操作算作成功。
      2. **过时文档**：`_cleanup_partial` 的 docstring（`file_manager.py:281-291`）仍写
         「`copytree` 的 `makedirs(exist_ok=False)` 抛 FileExistsError 时目标不是我们的，不清」——
         **这句在 AW-17 之后已经不成立**（copytree 现在用 `dirs_exist_ok=True`，
         所有权证据改由我们自己的 `os.makedirs(dest)` 提供）。既然 AW-17 主打「docstring 改准确」，
         这处漏网的顺手补上。
      3. 模块 docstring 里「POSIX 下空目录被替换会丢数据」措辞略强——空目录被替换**没有数据可丢**
         （只是 no-clobber 被破坏）。改准确。
      ✅ 已完成（2026-10-17）：实际 **110** 个用例（102 → 110，净增 8 条，全在
      `tests/test_file_manager.py`：`TestDidMove` 5 条 + `TestCallersCountMovesCorrectly` 3 条），
      `python -m unittest discover -s tests -v` 全绿。
      - **(1) 怎么让它可验证（GUI 不能 import）**：把判定逻辑抽成 `file_manager.did_move(result)`
        ——**纯函数**，`file_manager.py` 无 PyQt5 依赖、可直接 import，故可单测。
        它判的是 `result[1] is not None`（返回值里的 dest），**不判元组本身**，公开 2 元组契约不变。
        `dashboard.py` / `desktop_panel.py` 的拖拽计数改为
        `if p and did_move(move_into_category(...))`（各加一行注释点明陷阱）。
        `categorize_file` 的调用方只有 `file_watcher.py:79`，它本就写 `if cat_name:`（判元素、
        非判元组），**无此 bug，未改**。新增用例含「纯函数判定」与「端到端复刻调用方计数」
        两层：让 `shutil.move` 抛 OSError → 断言 `did_move` 为假、且调用方计数为 0（不误算成功）。
      - **(2)** `_cleanup_partial` docstring 改写：所有权证据来自 `_move_dir_no_clobber` 里
        **我们自己的 `os.makedirs(dest)`**（`exist_ok=False`），`copytree` 随后用
        `dirs_exist_ok=True` 往里拷；目标已存在时 `makedirs` 抛 `FileExistsError`、那不是我们的、绝不清。
      - **(3)** 模块 docstring 改为：POSIX 下**文件**被静默覆盖**真的会丢数据**；
        **空目录**被替换只是破坏 no-clobber（没有数据可丢）。
      反向验证（**定点**，未用 `git checkout origin/master -- file_manager.py` 那种超集回退）：
      只把 `did_move` 的函数体改回旧的 buggy 写法 `return bool(result)`，
      `git diff -- file_manager.py` 确认 `BREAK` 标记已生效（`grep BREAK` 命中）
      → 重跑得 **3 failed**，正是三条判别性用例（`TestDidMove.test_failure_tuple_is_not_a_move`
      + `TestCallersCountMovesCorrectly` 的 `test_failed_move_into_category_not_counted` /
      `test_failed_categorize_not_counted`）；装回修复、`grep BREAK` 0 命中后恢复 110 全绿。
      全程未 import GUI 模块（`dashboard.py` / `desktop_panel.py` 仅 `py_compile` 静态检查）、
      未在真实桌面验证，仓库根目录未生成 `config.json`（`git status` 仅 4 个预期改动文件）。

- [x] **AW-3 修分类 `folder` 字段的路径越界（数据安全）**
      问题：`file_manager.py:30-33` 直接 `os.path.join(storage_root, folder)`，
      `folder` 来自用户自由文本（`dashboard.py:1093-1095`/`1112`/`1125`），
      填 `..\..\x` 就能把文件移出存储根目录。
      修法：在 `get_category_folder` 或更早的入口做 `os.path.commonpath` 校验，
      越界则拒绝并返回明确错误（不要静默 fallback 到别处）。
      新增用例：`folder` 为 `..\..\evil` / 绝对路径 / 含 `..` 的嵌套路径 → 断言被拒绝；
      正常的 `folder` → 断言仍正常解析。
      ✅ 已完成（2026-10-17）：实际 **126** 个用例（110 → 126，净增 16 条，全在
      `tests/test_file_manager.py` 新增 `TestCategoryFolderSafety`），
      `python -m unittest discover -s tests -v` 全绿。
      修法：新增模块级 `UnsafeCategoryFolder(ValueError)` + **纯函数**
      `category_folder_error(storage_root, folder_name)`（返回 None 或一句中文错误说明），
      `get_category_folder` 调它做校验，越界即 `raise UnsafeCategoryFolder`——
      **明确报错，绝不静默兜底**（兜底会把「配置有问题」藏起来、继续把文件搬到错位置）。
      校验规则（跨平台一致，`\` 与 `/` 都当分隔符，故 `..\..\evil` 在 POSIX 上也会被拒）：
      非空 → 非绝对路径（不以分隔符开头、无盘符）→ 不含任何 `..` 组件（哪怕绕回存储根内
      也不放行）→ 兜底用 `os.path.commonpath` 确认解析结果**严格**落在存储根内
      （等于存储根本身也算越界）。
      GUI 校验：`dashboard.py._on_add_category` 在保存前调同一个纯函数
      `category_folder_error(get_storage_root(self.config), folder or name)`，
      不合法则弹窗拦截。`panel_manager.add_category` 只由这条已校验的路径调用，无需重复校验。
      ⚠️ `dashboard.py` 是 GUI 模块，**未 import**，只做 `py_compile` 静态检查
      （`dashboard.py`/`desktop_panel.py`/`panel_manager.py`/`main.py` 均通过）。
      反向验证（**定点**，未用 `git checkout origin/master -- <文件>` 那种超集回退）：
      只把 `get_category_folder` 里的 `error = category_folder_error(root, folder_name)`
      改成 `error = None  # BREAK`（跳过越界校验、恢复旧的裸 join 行为），
      `git diff -- file_manager.py` 确认 `BREAK` 标记已生效（`grep BREAK` 命中）
      → 重跑得 **11 failed**，全部是 `TestCategoryFolderSafety` 的越界拒绝用例；
      装回修复、`grep BREAK` 0 命中后恢复 126 全绿。
      全程 `tempfile.TemporaryDirectory()` 造目录、config 字典指向临时路径，
      未在真实桌面验证，仓库根目录未生成 `config.json`（`git status` 仅 3 个预期改动文件）。

- [x] **AW-19 处置 `UnsafeCategoryFolder`（AW-3 引入的回归）+ junction 逃逸（AW-3 复查实测）**

      AW-3 的对抗性复查确认「核心路径越界都挡住了」（绝对路径、`..`、UNC、盘符、
      空/`.`/纯分隔符，定点破坏 11 红），**但实测出两个必须处理的问题**：

      **1. 🔴 AW-3 引入的回归：`UnsafeCategoryFolder` 全仓无人捕获。**
      `grep -rn UnsafeCategoryFolder` 只有定义、raise 和测试——**没有任何 `except`**。
      实测四条链都原样抛出：
      - `init_folders`（`:185`，未包 try）← `main.py:101`（在 `MainApp.__init__` 里，未包 try）
        → **启动即崩，App 根本起不来**；
      - `categorize_file`（`:222`）← `file_watcher.py:78`（`_process_pending` 是 QTimer 槽，未包 try）
        → PyQt5 槽内未捕获异常会 **abort 事件循环**；
      - `get_files_in_category`（`:241`）← `dashboard.py:963/1241/1377`、`_update_status` 的 `:1566`、
        `desktop_panel.py:326` → **GUI 刷新崩**；
      - `move_into_category`（`:302/:315`）← `dashboard.py:1337`、`desktop_panel.py:402`（拖拽）→ 崩。
      触发条件：`config.json` 里存在一个非法 `folder`（**手工编辑，或 AW-3 之前的旧配置**——
      也就是**老用户升级后可能直接起不来**）。GUI 新建路径已被拦，正常点不出来。
      修法：**在调用点捕获并降级**——跳过该分类 + 记日志/给用户可见提示，
      **而不是让整个 App 崩**。至少保证：坏配置 → 应用仍能启动、其余分类照常工作、
      且用户能看到「某个分类的目录名不安全，已跳过」。
      ⚠️ AW-3 把「静默写到存储根外」换成了「静默崩溃」，两个都不能接受；
      **正确目标是「可见的降级」**。改完请明确说明：坏配置下应用能否启动、用户会看到什么。
      新增用例：配置里塞一个非法 `folder` → 断言 `init_folders` **不抛异常**、
      该分类被跳过、其余分类正常；断言有可见的错误记录。

      **2. junction / 符号链接逃逸（复查已用 `mklink /J` 实测复现）。**
      若 `storage_root\<folder>` **已存在且是指向存储根之外的 junction/符号链接**，
      路径级校验会放行，文件实际写到存储根之外：复查实测
      `_move_no_clobber(victim.txt, storage\evil, ...) ok=True`，而 `victim.txt`
      实际落在 `outside\` 里。触发前提是**预先存在该链接**（用户为省空间把分类目录
      junction 到别的盘，或同步软件植入）。
      修法（二选一，写清理由）：对最终目标做 `os.path.realpath` 复检并拒绝落在根外的；
      或**明确记录为已知残留风险**（因为「用户故意把分类目录链到别的盘」可能是合法用法）。
      选后者的话，必须在代码注释和 README 里写明这个前提，别让它悄悄存在。

      **3. 次要**：非字符串 `folder`（如 `"folder": 123`）——`category_folder_error` 先 `str()` 判为安全，
      但 `get_category_folder` 对原始值 `os.path.join(root, 123)` 抛 `TypeError`（不是 `UnsafeCategoryFolder`）。
      仅手工改 JSON 可达，顺手统一成同一种错误类型。
      ✅ 已完成（2026-10-17）：实际 **141** 个用例（126 → 141，净增 15 条：
      `tests/test_file_manager.py` 新增 `TestUnsafeCategoryDegradation` 12 条 +
      `tests/test_init_folders.py` 新增 `TestUnsafeCategoryDoesNotCrashStartup` 3 条），
      `python -m unittest discover -s tests -v` 全绿。
      - **(1) 🔴 回归修复（可见的降级）**：新增 `safe_category_folder(config, category)`
        ——`get_category_folder` 的「绝不抛」变体：坏配置时记一条 ERROR 日志并返回 `None`，
        调用点据此**跳过该分类**。四个入口全改用它：`init_folders`（跳过并计入新增的
        `MoveStats.skipped` 字段）、`categorize_file`（跳过继续找别的安全分类）、
        `get_files_in_category`（返回 `[]`）、`move_into_category`（返回 `(None, None)`）。
        GUI 里三处直接调 `get_category_folder` 的地方（`dashboard._on_new_folder` /
        `_update_status`、`panel_manager.add_category`）也改成 `safe_category_folder` +
        `None` 处理。`main.py` 在 `init_folders` 后若 `skipped>0` 弹一个 `QMessageBox` 提示。
        新增纯函数 `unsafe_category_message` 生成「分类「X」的目录名不安全，已跳过：…」文案。
        **坏配置下应用能启动**（`init_folders` 不再抛 → `MainApp.__init__` 不崩）；
        **用户会看到**：启动时一个警告弹窗 + ERROR 日志，该分类被跳过、其余分类照常工作。
      - **(2) junction / 符号链接逃逸**：选「**realpath 复检并拒绝落在根外的**」
        （新增 `realpath_escape_error`；`get_category_folder` 在词法校验后对最终目标
        `os.path.realpath` 复检，`commonpath` 不等于 realpath(root) 即判越界）。
        理由：核心安全承诺是「桌面文件只在存储根内搬动」，junction（`mklink /J` 免管理员）
        会被同步软件/恶意程序悄悄植入；且本项已把「拒绝」变成可见的降级，代价很低。
        真正要换盘的用户应改 `storage_path`，而非链单个分类目录。
        **用真实 `mklink /J` 复现**：词法校验放行、realpath 复检拒绝
        （用例 `test_real_junction_escape_is_rejected`，实际执行、非 skip）。
      - **(3) 非字符串 folder 统一**：`category_folder_error` 对非字符串返回
        「子文件夹名必须是文本。」，于是 `get_category_folder` 对 `"folder": 123` 抛的是
        `UnsafeCategoryFolder`（不再是 `TypeError`）——校验与解析行为一致。
      反向验证（三步**定点破坏**，未用 `git checkout origin/master -- <文件>` 那种超集回退；
      每步先 `git diff` 确认 `BREAK` 标记生效）：
      (A) 把 `safe_category_folder` 改回「直接 `return get_category_folder(...)`」→ 重跑得
          **9 ERROR**，正是四条链的降级用例 + 真实 junction 用例；
      (B) 把 `escape = realpath_escape_error(...)` 改成 `escape = None` → 重跑得 **1 FAIL**，
          正是 `test_real_junction_escape_is_rejected`（证明 realpath 复检是判别性的）；
      (C) 把 `isinstance` 守卫改回 `if False:` + `str(folder_name).strip()` → 重跑得
          **1 FAIL + 2 ERROR**，正是三条非字符串用例。
      装回后 `grep BREAK` 0 命中、恢复 141 全绿。
      全程 `tempfile.TemporaryDirectory()`（junction 也在临时目录内建、`os.rmdir` 删链接）+
      `mock.patch("config.CONFIG_PATH", 临时路径)`；未运行 `main.py` / `restore_files.py`，
      未在真实桌面验证，仓库根目录未生成 `config.json`（`git status` 仅 7 个预期改动文件）。

- [ ] **AW-4 修 `move_into_category` 允许移入存储根祖先（数据安全）**
      问题：`file_manager.py:153-159` 只拒绝「分类文件夹本身」和「存储根」，
      把 `Documents`（存储根的父目录）拖进面板，会把整个存储目录连分类一起搬进某个分类，
      导致存储根位移、配置全部失效。
      修法：拒绝**存储根及其所有祖先目录**（`os.path.commonpath` 或逐级 `dirname` 判断）。
      新增用例：把存储根、存储根父目录分别作为源 → 断言都被拒绝；正常桌面文件 → 仍可移入。

- [ ] **AW-5 修回收站删除的标志位与结果判定（正确性）**
      问题：`dashboard.py:1611-1613` 把 `SHERB_NOCONFIRMATION/NOPROGRESSUI/NOSOUND`
      （那是 `SHEmptyRecycleBin` 的标志）当成 `FOF_*` 用，导致 `FOF_NOCONFIRMATION(0x10)`
      实际没设，系统仍会弹确认框；且 `dashboard.py:1643-1645` **从不检查
      `fAnyOperationsAborted`**，用户点「取消」后 `result==0` 仍被当成删除成功计数
      （`dashboard.py:1473-1474`），界面显示删了实际没删。
      修法：改用正确的 `FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT`，
      并检查 `fAnyOperationsAborted`；被取消时不计入成功数。
      注意：这段是 GUI 代码，**把「标志位常量」和「结果判定」抽成可单测的纯函数**
      （例如 `build_delete_flags()` 和 `interpret_delete_result(result, aborted)`），
      再对这两个纯函数写用例——不要在测试里真的调用 `SHFileOperation`。

- [ ] **AW-6 修 `restore_files.py` 硬编码路径与分类清单（数据安全）**
      问题：`restore_files.py:12` 把桌面写死成 `~/Desktop`，无视 `config.desktop_path`
      （桌面被 OneDrive 重定向时会恢复到错位置）；`restore_files.py:13-15` 硬编码 5 个默认分类名，
      **用户自建分类里的文件永远恢复不了**。
      修法：读 `config.load_config()` 拿 `desktop_path`，分类清单改为遍历配置里的实际分类
      （含自建分类），并处理 `folder` 字段与显示名不一致的情况。
      新增用例：构造一份含自建分类的配置 + 临时目录结构 → 断言恢复清单覆盖自建分类，
      且目标目录用的是配置里的 `desktop_path` 而不是写死的 `~/Desktop`。
      **这个脚本会移动真实文件，测试必须全程在临时目录里跑。**

- [ ] **AW-7 修文件监控搬走「半成品」（健壮性，但有真实数据风险）**
      问题：`file_watcher.py:32,66-85` 防抖只有 500ms 且**不判断文件是否写完**，
      大文件正在复制时会被 `categorize_file`（`file_manager.py:86`）移走半个文件。
      修法：归类前检查文件稳定性——间隔采样 `os.path.getsize`，连续两次相同（或 mtime 稳定）
      才归类；不稳定则稍后重试。
      新增用例：把「稳定性判断」抽成纯函数（例如 `is_stable(path, ...)`，可注入 sizes 序列），
      断言「大小仍在变 → 判为不稳定」「两次相同 → 稳定」。真实文件系统行为用临时文件补一条集成用例。

- [ ] **AW-8 把静默吞掉的异常改成可观测（健壮性）**
      问题：`file_manager.py:130`（批量移动失败 `pass`）、`file_manager.py:234`
      （桌面图标排列整体 `except Exception: pass`）、`file_manager.py:110-111`
      （列目录失败返回 `[]`）、`restore_files.py:27`（读配置失败静默用默认路径）——
      出问题时用户和开发者都看不到。
      修法：统一改成「记录 + 返回可判断的结果」。项目零依赖且没有日志基建，
      可以用标准库 `logging`，或把失败计数返回给调用方——**选一种并保持一致**，在条目里说明选择理由。
      ⚠️ 注意 AW-2 也在动 `file_manager.py` 的异常处理，**先读一遍当前代码再改，别覆盖掉 AW-2 的成果**。
      新增用例：模拟各失败路径 → 断言失败被记录/被返回，而不是无声无息。

- [ ] **AW-9 修搜索时 `getsize` 崩溃（正确性）**
      问题：`dashboard.py:1377` 对搜索结果条目调 `os.path.getsize`，
      若文件在「列出」与「取大小」之间被删/被移，`OSError` 未捕获 → 整个搜索崩溃。
      修法：加异常处理，取不到大小时显示占位（如 `—`）而不是崩。
      这一段是 GUI 代码，把「安全取大小」抽成纯函数（例如 `safe_size(path)`）再单测。
      新增用例：不存在的路径 → 返回占位值不抛异常；正常文件 → 返回真实大小。

- [ ] **AW-10 修 `config.py` 浅拷贝污染默认配置（正确性）**
      问题：`config.py:74-77` 用 `dict(DEFAULT_CONFIG)` 做浅拷贝，
      `categories` 内层（含 `subtypes`）与 `DEFAULT_CONFIG` **共享引用**，
      运行时原地修改会永久污染模块级默认值，导致「恢复默认」拿到的是被改过的配置。
      修法：改用 `copy.deepcopy`。
      新增用例：`load_config` 后原地改内层 `subtypes` → 断言 `DEFAULT_CONFIG` 未被污染；
      再次 `load_config` 拿到的是干净的默认值。

- [ ] **AW-11 新建/编辑分类时校验扩展名重叠（正确性）**
      问题：`dashboard.py:1108-1122` / `1171-1181` 不检查扩展名是否与其他分类重叠，
      而 `categorize_file`（`file_manager.py:78-91`）按列表顺序取**首个**匹配，
      同一个扩展名被两个分类声明时，文件会路由到顺序决定的不确定分类。
      修法：把「扩展名冲突检测」抽成纯函数，新建/编辑时提示冲突并阻止保存（或要求用户明确覆盖）。
      **行为变更点**：如果原设计是允许重叠的，这里属于产品决策 → 先读代码判断，
      拿不准就记到「待确认」而不要擅自改交互。
      新增用例：重叠 → 检测出冲突；不重叠 → 通过。

- [ ] **AW-12 补 `requirements.txt` 与文档不一致（打磨）**
      问题：`config.py:106-119` 用 `pythoncom` / `win32com.client` 创建开机自启快捷方式，
      但 `requirements.txt` 只有 `PyQt5` 和 `watchdog`，**没写 `pywin32`**；
      未安装时 `config.py:120-124` 会静默降级去写 `.bat`。另外 `README.md:45` 提到的
      根目录快捷方式 `桌面文件收纳.lnk` 被 `.gitignore:18` 忽略，文档与实物不一致。
      修法：`requirements.txt` 补 `pywin32`（或用注释明确写出「可选依赖 + 降级行为」），
      README 把快捷方式那句改成与实际一致的说法。
      这条是文档/依赖声明，**验证方式**：`pip install -r requirements.txt` 的依赖能被解析
      （不要真的重装环境），并人工核对 README 描述与 `config.py` 实际行为一致。

- [ ] **AW-13 给桌面图标自动重排加配置开关（打磨，注意不要改默认行为）**
      问题：`main.py:104` + `file_manager.py:188-235` 每次启动**无条件**
      `LVM_ARRANGE/LVA_SNAPTOGRID` 重排用户桌面图标，用户无法关闭。
      修法：加一个配置项（如 `"arrange_icons": true`），**默认值保持 `true` 以不改变现有行为**，
      允许用户关掉；`main.py` 按配置决定是否调用。
      ⚠️ 默认值属于产品决策——**保持现状的默认值**是安全选择，不要改成 `false`。
      新增用例：`arrange_icons` 为 `false` → 断言不调用排列逻辑（打桩）；
      缺省（配置里没有这个键）→ 断言仍然排列（向后兼容）。

- [ ] **AW-14 加 CI（打磨）**
      问题：仓库没有 `.github/workflows/`，改动没有任何自动把关。
      修法：加一个 GitHub Actions workflow，在 push 时跑
      `python -m unittest discover -s tests -v`。
      ⚠️ 这个项目是 **Windows 专用 GUI**（大量 `ctypes.windll`），但 AW-0 之后测试应只覆盖纯逻辑，
      所以 **Ubuntu runner 上应该能跑通**；如果跑不通（比如有 Windows-only 的 import），
      改用 `windows-latest` runner，并在条目里写清为什么。
      ⚠️ **不要引入 pytest**，用标准库 unittest。
      验证方式：本地先用同样命令跑通，再 push，**然后确认 Actions 这次运行的结果**
      （用 `git credential fill` 取 token 调 GitHub API 查 workflow run 状态；
      查不到就如实说明「已推送但未能确认 CI 结果」，不要假装绿了）。

## 待确认（不要擅自做，等用户拍板）

- **编辑分类时要不要同步改磁盘上的文件夹名？** `dashboard.py:1180-1181` 编辑分类只改
  `name`/`extensions` 不改 `folder`，导致界面名与磁盘目录名长期不一致；但真去改目录名
  意味着要移动里面所有文件，风险大、且需要迁移逻辑。属于产品决策。
- **首次运行静默搬桌面文件要不要改成默认不搬？** 目前 `file_manager.py:44-57` 首次启动
  无确认搬走匹配文件。AW-2 会加 dry-run/预览，但「默认搬还是默认不搬」是产品决策。
- **`arrange_icons` 的默认值**：AW-13 里我按「保持 `true` 不改变现状」处理，
  如果你想默认关掉，说一声。
- **要不要引入 pytest？** 我选了标准库 unittest（零新依赖，符合仓库风格）。
  如果你更想用 pytest，说一声，AW-0 要重写。
- **`requirements.txt` 要不要硬加 `pywin32`？** 它会让安装变重（带一堆 win32 扩展），
  而现有代码在缺失时是能降级工作的。也可以只在注释里标成可选依赖。

## 收尾

队列清空（全部 `[x]` 或 `BLOCKED`）后，**停下来**，在文件末尾写一节
「## 作业总结」：逐条列出完成了什么、验证结果（用例数）、`BLOCKED` 项及原因、待确认项，
然后向用户报告。**不要自己发明新条目继续做。**
