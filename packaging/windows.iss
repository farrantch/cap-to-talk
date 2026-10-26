#ifndef AppVersion
  #error AppVersion must be supplied by the build script
#endif
#ifndef BundleDir
  #error BundleDir must be supplied by the build script
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by the build script
#endif

[Setup]
AppId={{5ACBD627-5167-4A9C-930D-268585BB940D}
AppName=Cap To Talk
AppVersion={#AppVersion}
AppPublisher=Chase Farrant
AppPublisherURL=https://github.com/farrantch/cap-to-talk
DefaultDirName={localappdata}\Programs\CapToTalk
DefaultGroupName=Cap To Talk
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=cap-to-talk-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\CapToTalk.exe
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Cap To Talk"; Filename: "{app}\CapToTalk.exe"

[Run]
Filename: "{app}\CapToTalk.exe"; Description: "Open Cap To Talk"; Flags: nowait postinstall skipifsilent
