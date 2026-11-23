; 把 dist\IHaveApple 打成 Windows 安装包。
; 由 scripts/build-windows.ps1 调用：
;   ISCC.exe /DAppVersion=0.1.3 /DAppTag=v0.1.3 packaging\IHaveApple.iss
; 编译器自带中文语言文件时，脚本会额外传 /DUseChinese。
;
; 安装目录由用户在向导里选择（PrivilegesRequired=lowest，默认装到当前用户目录）。

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppTag
  #define AppTag "dev"
#endif
#ifndef AppVersion4
  #define AppVersion4 "0.0.0.0"
#endif

[Setup]
AppId={{6E2F8A94-3B7C-4D51-9C0A-2D7B5E1F8A63}
AppName=IHaveApple
AppVersion={#AppVersion}
AppVerName=IHaveApple {#AppTag}
AppPublisher=LemonYangZW
AppPublisherURL=https://github.com/LemonYangZW/IHaveApple
AppSupportURL=https://github.com/LemonYangZW/IHaveApple/issues
AppUpdatesURL=https://github.com/LemonYangZW/IHaveApple/releases
DefaultDirName={autopf}\IHaveApple
DefaultGroupName=IHaveApple
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=IHaveApple-Setup-{#AppTag}-win64
SetupIconFile=app.ico
UninstallDisplayIcon={app}\IHaveApple.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
VersionInfoCompany=LemonYangZW
VersionInfoDescription=IHaveApple 安装包
VersionInfoProductName=IHaveApple
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion4}

#ifdef UseChinese
[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\IHaveApple\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\IHaveApple"; Filename: "{app}\IHaveApple.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\IHaveApple"; Filename: "{app}\IHaveApple.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\IHaveApple.exe"; Description: "{cm:LaunchProgram,IHaveApple}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 默认缓存目录（设置页换到别处时，用户自己的目录不删）
Type: filesandordirs; Name: "{localappdata}\IHaveApple\cache"
Type: filesandordirs; Name: "{app}\_internal\.cache"
Type: filesandordirs; Name: "{app}\.cache"
Type: filesandordirs; Name: "{app}\hgd\cache"
Type: files; Name: "{app}\hgd\anonymous*.json"
Type: files; Name: "{app}\hgd\actor_id.txt"
