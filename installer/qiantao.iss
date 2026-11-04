; 千淘 Inno Setup 安装工程
; 编译：安装 Inno Setup 6 后，ISCC.exe installer\qiantao.iss
; 前置：先运行 python scripts/make_dist.py 生成 build/Qiantao/

#define MyAppName "千淘"
#define MyAppNameEn "Qiantao"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Qiantao"
#define MyAppExeName "启动千淘.bat"

[Setup]
AppId={{8C1F0E9A-6C7B-4E9F-9E2A-7B9D5A3F1C21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppNameEn}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\qiantao.ico
OutputDir=..\build
OutputBaseFilename=Qiantao-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=..\build\Qiantao\qiantao.ico
LicenseFile=..\LICENSE
; 数据与登录态保留在用户目录之外的应用目录，卸载时询问

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "autostart"; Description: "开机自动启动千淘"; GroupDescription: "启动选项："; Flags: checkedonce
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "..\build\Qiantao\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\qiantao.ico"
Name: "{group}\{#MyAppName} 环境自检"; Filename: "{app}\环境自检.bat"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\qiantao.ico"; Tasks: desktopicon

[Registry]
; 开机自启（当前用户）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Qiantao"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动千淘"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时不删 data/（登录态与结果），仅提示用户手动清理
Type: filesandordirs; Name: "{app}\app\images"
Type: filesandordirs; Name: "{app}\app\logs"
