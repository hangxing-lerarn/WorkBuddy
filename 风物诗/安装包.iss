; 风物诗 —— Inno Setup 安装包脚本
;
; 编译（推荐走 tools/build.py --inno，它会自动带上版本号与语言开关）：
;     ISCC.exe 安装包.iss
;     ISCC.exe /DAPPVERSION=0.1.0 /DCHINESE 安装包.iss
;
; ★ 三条刻意的设计决定：
;   1. PrivilegesRequired=lowest —— 装到用户目录，**安装时不要 UAC**。
;      应用本身只在「点开始演奏」那一刻才自提权（这是与用户逐项确认过的）。
;   2. 不写任何 [UninstallDelete] —— 卸载**绝不碰**用户的曲谱数据
;      （文档\风物诗\ 与 %LOCALAPPDATA%\风物诗\），只删程序目录。
;   3. 源目录是 dist\风物诗\ —— 由 tools/build.py 先装配好（含 获取谱子/、
;      parser.py、player.py）。工具脚本是运行时被就地加载的普通文件，
;      必须与 exe 同级真实存在。

#ifndef APPVERSION
  #define APPVERSION "0.1.0"
#endif
#define AppName "风物诗"
#define AppExe "风物诗.exe"

[Setup]
AppId={{8F3A6C21-7B4E-4D2A-9E15-3C7D5A9B1E64}
AppName={#AppName}
AppVersion={#APPVERSION}
AppVerName={#AppName} {#APPVERSION}
AppPublisher=风物诗
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
; ★ 不要设 AllowNoIcons=yes：它和 DisableProgramGroupPage=yes 一起用时，
;   Inno 会把「不要创建开始菜单项」当成已选，结果**一个快捷方式都不建**
;   （实测：日志里连一条 .lnk 都没有）。想跳过开始菜单，装的时候传 /NOICONS 即可。
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename={#AppName}-安装包-{#APPVERSION}
SetupIconFile=assets\风物诗.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
InfoBeforeFile=使用须知.txt

#ifdef CHINESE
[Languages]
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; dist\风物诗\ 下的一切：exe、_internal\、获取谱子\、parser.py、player.py
Source: "dist\风物诗\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即启动 {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载前先把可能还在跑的实例关掉（按 exe 名，不动别的进程）
Filename: "{cmd}"; Parameters: "/c taskkill /F /IM {#AppExe} /T"; \
    Flags: runhidden; RunOnceId: "KillApp"

; ★ 刻意不写 [UninstallDelete]：[UninstallDelete] 会连用户数据一起删。
;   用户的曲谱在「文档\风物诗\」、配置在「%LOCALAPPDATA%\风物诗\」，
;   卸载后保留，重装即可继续用。
