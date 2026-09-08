# 桌面文件收纳 Desktop File Organizer

> Windows 桌面文件自动整理工具 —— 托盘 + 桌面悬浮面板 + 仪表盘，10 套精心设计的主题。

把散落在桌面上的文件自动归入分类，用悬浮面板和仪表盘统一管理；分类文件夹存放在桌面之外，桌面保持整洁、永不遮挡你的工作窗口。

---

## 特性

- **自动归类**：监控桌面，新文件按扩展名自动移入对应分类（Word/Excel/PDF、压缩包、文本、图片等）。
- **桌面悬浮面板**：每个分类一个面板，**置底不遮挡其他应用窗口**；面板可**磁吸对齐**（靠近自动贴边）并**编组整体拖动**。
- **拖拽收纳**：把资源管理器里的文件/文件夹直接拖到面板或仪表盘上，即移入该分类。
- **仪表盘**：分类管理、全库搜索、办公文件按 Word/Excel/PDF 子类型筛选、新建分类/文件夹、删除（进回收站）。
- **独立面板开关**：仪表盘侧边栏每个分类都有「面板 ●/○」开关，可单独显示/隐藏该分类的悬浮面板；侧边栏可左右拖宽，超长分类名自动省略不遮挡。
- **苹果风界面**：悬浮式半透明自动隐藏滚动条、更大更清晰的字号（0.85–1.5 五档）、柔和无硬边框布局。
- **10 套主题**：仪表盘 + 悬浮面板 + 托盘全局换肤，另可调**面板透明度**与**字号**。
- **桌面整洁**：分类文件夹存放在桌面外的存储目录（默认 `文档\桌面文件收纳`），桌面只留快捷方式。
- **首次安装可选存储目录**：首次运行弹出「选择文件收纳的存储位置」，可浏览选择任意目录（如 `E:\beifen\桌面文件收纳`）；不做选择则默认使用系统文档目录。
- **桌面图标自动排列**：启动时把桌面图标对齐到网格。

## 环境要求

- Windows 10 / 11（依赖 Win32 API，仅支持 Windows）
- Python 3.9+（开发环境为 3.14）
- 依赖：`PyQt5`、`watchdog`

## 安装

```bash
pip install -r requirements.txt
```

## 打包与分发

用 PyInstaller 打包成**免安装的单个可执行文件**（单文件，双击即用）：

```bash
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name DesktopFileOrganizer --icon app_icon.ico main.py
```

产物为单个 `dist/DesktopFileOrganizer.exe`（约 38 MB）。本仓库同时提供：

- 项目根目录快捷方式 `桌面文件收纳.lnk` → 指向该 exe，双击即可打开（图标用 `app_icon.ico`）。
- 便携安装包 `dist/DesktopFileOrganizer-安装包.zip`（含 exe 与使用说明，解压即用；不含本机 `config.json`）。
- Inno Setup 安装程序 `dist/DesktopFileOrganizer-安装程序.exe`（安装向导 + 开始菜单/桌面快捷方式 + 卸载项；安装到用户目录，免管理员）。脚本见 `installer/DesktopFileOrganizer.iss`，编译：`ISCC.exe installer\DesktopFileOrganizer.iss`。

> 注：PyInstaller 单文件版偶被部分杀毒软件误报。打包时若需规避，可改用 `--onedir`（产物在 `dist/DesktopFileOrganizer/`）。

## 使用

```bash
python main.py
```

启动后：

1. **首次运行**弹出「选择文件收纳的存储位置」：选任意目录，或直接确定使用默认（系统文档 `文档\桌面文件收纳`）。随后在存储目录创建分类文件夹。
2. 桌面上出现各分类的**悬浮面板**，系统托盘出现图标。
3. **双击托盘图标**打开仪表盘；托盘右键可显示/隐藏面板、新建分类、开关开机自启、退出。

常用操作：

| 操作 | 方式 |
|---|---|
| 打开文件 | 面板或仪表盘中双击文件 |
| 收纳文件/文件夹 | 从资源管理器**拖拽**到面板或仪表盘 |
| 整理面板 | 拖动面板靠近另一块 → 磁吸对齐；边缘相接后面板**编组拖动** |
| 换主题 / 调透明度 / 字号 | 仪表盘右上角 **设置** |
| 新建文件夹 | 仪表盘「新建文件夹」（在当前分类内创建子文件夹） |

## 分类与存储

默认分类（可在仪表盘新建/编辑/删除）：

| 分类 | 扩展名 |
|---|---|
| 办公文件 | doc, docx, xls, xlsx, csv, pdf（内部按 Word/Excel/PDF 筛选） |
| 压缩包 | zip, rar, 7z |
| 文本文件 | txt, md, log |
| 图片 | jpg, jpeg, png, gif, bmp, svg |
| 其他 | 手动整理（存放项目文件夹等，不自动归类） |

分类文件夹存放在 **存储目录**（默认 `C:\Users\<用户名>\Documents\桌面文件收纳`），可通过 `config.json` 的 `storage_path` 自定义，或**首次安装时在选择对话框中直接指定**。桌面本身只保留快捷方式。

## 主题

仪表盘「设置」中可选 10 套主题，每套 = 深色底 + 单一强调色：

翡翠绿 · 深海蓝 · 暮夜紫 · 暖阳橙 · 鎏金铜 · 曜石黑 · 森林绿 · 冰川蓝 · 珊瑚红 · 靛青蓝

## 配置

`config.json` 由程序在首次运行时自动生成（本仓库不提交本机配置），字段：

| 字段 | 说明 |
|---|---|
| `categories` | 分类列表（name / extensions / folder / subtypes） |
| `panels` | 悬浮面板位置与折叠状态 |
| `desktop_path` | 桌面路径 |
| `storage_path` | 分类存储根目录 |
| `theme` | 当前主题（见 `themes.py`） |
| `panel_opacity` | 面板透明度 0.5–1.0 |
| `font_scale` | 字号比例 0.85 / 1.0 / 1.15 / 1.3 / 1.5 |
| `auto_start` | 是否开机自启 |
| `initialized` | 是否已完成首次文件归类 |

## 项目结构

```
main.py          入口：托盘、面板、仪表盘协调
dashboard.py     仪表盘主窗口（搜索 / 分类 / 文件管理 / 设置）
desktop_panel.py 桌面悬浮面板（置底、磁吸、编组拖动、拖拽收纳）
file_manager.py  文件归类 / 移动 / 存储路径解析
file_watcher.py  watchdog 桌面监控（自动归类新文件）
panel_manager.py 面板生命周期与状态持久化
themes.py        10 套主题定义
icons.py         QPainter 矢量图标库
config.py        配置读写与默认值
restore_files.py 工具：把分类文件夹中的文件移回桌面
```

## 说明

- 删除文件进入**回收站**，不会永久删除。
- 若想恢复文件到桌面，运行 `python restore_files.py`。
- 本机 `config.json` 不入库（含个人路径）；参考 `config.example.json`。
