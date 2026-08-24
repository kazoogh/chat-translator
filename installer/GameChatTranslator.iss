#define MyAppName "Game Chat Translator"
#define MyAppExeName "GameChatTranslator.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\artifacts\Game Chat Translator\GameChatTranslator"
#endif

[Setup]
AppId={{B63B0DAA-77DF-4C81-A157-655453368AC6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=kazoogh
AppPublisherURL=https://github.com/kazoogh/chat-translator
AppSupportURL=https://github.com/kazoogh/chat-translator/issues
AppUpdatesURL=https://github.com/kazoogh/chat-translator/releases
DefaultDirName={localappdata}\Programs\GameChatTranslator
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\artifacts\installer
OutputBaseFilename=GameChatTranslator-Setup-x64
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany=kazoogh
VersionInfoDescription=Offline-first Windows game chat translator
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
ChangesAssociations=no
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start {#MyAppName} when I sign in"; GroupDescription: "Optional shortcuts:"; Flags: unchecked
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Optional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}\licenses"; DestName: "GameChatTranslator-Apache-2.0.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked

[Code]
function HasCommandLineParameter(const Parameter: String): Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
  begin
    if CompareText(ParamStr(Index), Parameter) = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if HasCommandLineParameter('/REMOVEUSERDATA') or
      ((not UninstallSilent) and
       (MsgBox(
         'Remove local settings, calibrations, learned terms, history, and downloaded models?',
         mbConfirmation,
         MB_YESNO
       ) = IDYES)) then
      DelTree(ExpandConstant('{localappdata}\GameChatTranslator'), True, True, True);
  end;
end;
