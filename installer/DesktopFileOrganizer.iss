; 桌面文件收纳 Desktop File Organizer — Inno Setup 安装脚本
; 用 ISCC 编译: ISCC.exe DesktopFileOrganizer.iss

[Setup]
; 应用标识（唯一，用于卸载注册）
AppId={{D8C5E1B4-3A7F-4C52-9B1E-2F6A0D4C8E91}
AppName=桌面文件收纳
AppVersion=1.0.0
AppVerName=桌面文件收纳 1.0.0
AppPublisher=DesktopFileOrganizer
AppPublisherURL=https://github.com/q2815798751/desktop-file-organizer
AppSupportURL=https://github.com/q2815798751/desktop-file-organizer
; 卸载时可卸载 app 本身；存储目录（分类文件）不随卸载删除
UninstallDisplayName=桌面文件收纳
UninstallDisplayIcon={app}\DesktopFileOrganizer.exe
; 默认安装目录：用户级程序（避免 Program Files 写权限导致 config.json 无法保存）
; 用 {userpf} 安装到 %LOCALAPPDATA%\Programs\DesktopFileOrganizer
DefaultDirName={userpf}\DesktopFileOrganizer
DisableProgramGroupPage=yes
; 输出目录与文件
OutputDir=..\dist
OutputBaseFilename=DesktopFileOrganizer-安装程序
SetupIconFile=..\app_icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 允许用户选择安装目录
AllowUNCPath=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; UserInfoPage 关闭，避免多余步骤
DisableDirPage=auto
DisableReadyPage=no
DisableFinishedPage=no
; 用户级安装（无需管理员）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; 中文界面
ShowLanguageDialog=auto
UsePreviousAppDir=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
; 主程序
Source: "..\dist\DesktopFileOrganizer.exe"; DestDir: "{app}"; Flags: ignoreversion
; 使用说明
Source: "使用说明.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 开始菜单快捷方式
Name: "{group}\桌面文件收纳"; Filename: "{app}\DesktopFileOrganizer.exe"; IconFilename: "{app}\DesktopFileOrganizer.exe"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"; IconFilename: "{app}\DesktopFileOrganizer.exe"
Name: "{autodesktop}\桌面文件收纳"; Filename: "{app}\DesktopFileOrganizer.exe"; IconFilename: "{app}\DesktopFileOrganizer.exe"; Tasks: desktopicon

[Run]
; 安装完成后运行
Filename: "{app}\DesktopFileOrganizer.exe"; Description: "立即运行 桌面文件收纳"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 不删除 config.json 以免删掉用户配置？ 若想保留配置则注释下一行
; Name: "{app}\config.json"; Type: files
