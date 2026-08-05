; ytarr Windows installer (Arr-style: one setup exe, Start Menu + Desktop shortcuts)
; Built by scripts\build-exe.ps1 after PyInstaller packs dist\ytarr\

#ifndef MyAppVersion
  #define MyAppVersion "0.1.6.4"
#endif

#define MyAppName "ytarr"
#define MyAppPublisher "machineshop44"
#define MyAppURL "https://github.com/machineshop44"
#define MyAppExeName "ytarr.exe"

[Setup]
AppId={{A7C3E91B-4D2F-4B8A-9E15-8199C0FFE001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install (same idea as Arrs Hub) — writable without admin
PrivilegesRequired=lowest
AllowNoIcons=yes
OutputDir=..\release
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-x64
SetupIconFile=..\assets\ytarr.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Keep user config/db/library on upgrade & uninstall
; Force-close running ytarr (tray) so upgrades don't require a manual quit
CloseApplications=force
CloseApplicationsFilter=ytarr.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
; Writable sidecars — created if missing; never wiped on reinstall
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\library"; Flags: uninsneveruninstall
Name: "{app}\music"; Flags: uninsneveruninstall

[Files]
; App payload from PyInstaller onedir (+ bundled ffmpeg / example config)
Source: "..\dist\ytarr\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "data\*;library\*;music\*;*.db;config.yaml;ytarr-tray.log;README.txt;Start ytarr.bat"
Source: "..\config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "..\VERSION"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--open-ui"; WorkingDir: "{app}"
Name: "{group}\{#MyAppName} (debug)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--debug --open-ui"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--open-ui"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--open-ui"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop the tray app before removing files
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyAppExeName} /T"; Flags: runhidden skipifdoesntexist; RunOnceId: "KillYtarrUninstall"

[UninstallDelete]
; Only remove empty leftover dirs we created; never force-delete user media/db
Type: dirifempty; Name: "{app}\data"
Type: dirifempty; Name: "{app}\library"
Type: dirifempty; Name: "{app}\music"
Type: dirifempty; Name: "{app}"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure KillYtarr();
var
  ResultCode: Integer;
begin
  { Tray apps sometimes ignore Restart Manager — force-kill before file copy. }
  Exec(
    ExpandConstant('{sys}\taskkill.exe'),
    '/F /IM {#MyAppExeName} /T',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
  Sleep(750);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  NeedsRestart := False;
  KillYtarr();
  Result := '';
end;
