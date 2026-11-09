; Inno Setup script for the single Windows installer.
; Build with: "C:\Users\<you>\AppData\Local\Programs\InnoSetup6\ISCC.exe" packaging\installer.iss

#define AppName "Real-time Voice Typing"
#define AppShortName "RealtimeVoiceTyping"
#define AppVersion "1.0.0"
#define AppPublisher "FiwFlash"
#define AppURL "https://github.com/fiwflash/realtime-voice-typing"
#define ProjectDir ".."

[Setup]
AppId={{B6E3D5B2-7D5B-4E3A-9E6B-2C1A4F8D9C71}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppShortName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#ProjectDir}\release
OutputBaseFilename=RealtimeVoiceTyping-Setup-{#AppVersion}
SetupIconFile={#ProjectDir}\assets\VoiceTyping.ico
UninstallDisplayIcon={app}\RealtimeVoiceTyping.exe
UninstallDisplayName={#AppName}
LicenseFile={#ProjectDir}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
MinVersion=10.0

[Languages]
Name: "thai"; MessagesFile: "compiler:Languages\Thai.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#ProjectDir}\dist\RealtimeVoiceTyping\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectDir}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\RealtimeVoiceTyping.exe"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\RealtimeVoiceTyping.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RealtimeVoiceTyping.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Models and settings live in %LOCALAPPDATA%\RealtimeVoiceTyping and are kept
; by default so a reinstall does not have to download several GB again.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\RealtimeVoiceTyping');
    if DirExists(DataDir) then
    begin
      if UninstallSilent then
      begin
        if CompareText(ExpandConstant('{param:cleandata|0}'), '1') = 0 then
          DelTree(DataDir, True, True, True);
      end
      else if MsgBox('ต้องการลบโมเดลและข้อมูลผู้ใช้ที่ดาวน์โหลดไว้ด้วยหรือไม่?' + #13#10 +
                '(ถ้าเลือก No โมเดลจะยังอยู่และใช้ต่อได้เมื่อติดตั้งใหม่)',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
