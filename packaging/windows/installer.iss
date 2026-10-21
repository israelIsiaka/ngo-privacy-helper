; Inno Setup script. Built by packaging/build.py, which passes AppVersion, SourceDir and OutputDir.
; Installs per user, so staff without administrator rights can install it.

#define AppName "NGO Privacy Helper"
#define AppExe "NGO Privacy Helper.exe"

[Setup]
AppId={{6B0E3C1A-4F2D-4C8E-9A57-2D1F0B9C7E31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Startbench Innovation Hub
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 version 1809 is the oldest Windows that Qt 6.8 supports.
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=NGO-Privacy-Helper-{#AppVersion}-Windows-Setup
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Double-clicking a .nph file opens it in the app. Per-user keys, removed on uninstall.
Root: HKA; Subkey: "Software\Classes\.nph"; ValueType: string; ValueName: ""; ValueData: "NGOPrivacyHelper.EncryptedFile"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\NGOPrivacyHelper.EncryptedFile"; ValueType: string; ValueName: ""; ValueData: "NGO Privacy Helper encrypted file"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\NGOPrivacyHelper.EncryptedFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\NGOPrivacyHelper.EncryptedFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
