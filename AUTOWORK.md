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

- [ ] **AW-1 修 `save_config` 非原子写 + `load_config` 静默回退（数据安全，最高优先级）**
      问题：`config.py:82-85` 直接 `open(...,'w')` 写入，写中断即产生半截 JSON；
      `config.py:71-79` 遇 `JSONDecodeError` 静默回退默认配置并**覆盖写回**，
      此时 `initialized` 变回 `False`，下次启动 `init_folders` 会**再次把整个桌面搬一遍**。
      修法：写入改为「写临时文件 → `os.replace` 原子替换」；解析失败时
      **先把损坏文件备份成 `config.json.corrupt-<时间戳>`**，再回退默认值，
      并且**保留原来的 `initialized` 状态**（从备份里尽量捞），不要让损坏触发二次搬移。
      新增用例：模拟半截 JSON / 非法 JSON，断言 (a) 备份文件存在且内容等于原损坏内容，
      (b) 不会因配置损坏而重新执行首次搬移。

- [ ] **AW-2 修 `_resolve_conflict` 的 TOCTOU 与 `shutil.move` 静默失败（数据安全）**
      问题：`file_manager.py:170-183` 先查存在再返回目标名，与随后的
      `shutil.move` 之间有竞态窗口；且 `file_manager.py:88-89` / `129-130` / `166-167`
      一律 `except: pass`，**移动失败用户完全看不到**。
      修法：冲突消解与移动都加异常处理，失败时**返回结构化结果（成功/失败 + 原因）**而不是静默 None；
      调用方（`init_folders` / `_move_matching_files`）据此统计失败数。
      新增用例：目标已存在同名文件 → 断言重命名到 `name (1).ext` 且原文件保留；
      模拟 `shutil.move` 抛 `OSError` → 断言返回失败结果而不是静默吞掉。

- [ ] **AW-3 修分类 `folder` 字段的路径越界（数据安全）**
      问题：`file_manager.py:30-33` 直接 `os.path.join(storage_root, folder)`，
      `folder` 来自用户自由文本（`dashboard.py:1093-1095`/`1112`/`1125`），
      填 `..\..\x` 就能把文件移出存储根目录。
      修法：在 `get_category_folder` 或更早的入口做 `os.path.commonpath` 校验，
      越界则拒绝并返回明确错误（不要静默 fallback 到别处）。
      新增用例：`folder` 为 `..\..\evil` / 绝对路径 / 含 `..` 的嵌套路径 → 断言被拒绝；
      正常的 `folder` → 断言仍正常解析。

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
