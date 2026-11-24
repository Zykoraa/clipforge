; ClipForge — Windows Installer Script (Inno Setup 6)
; Bundles ClipForgeNative.exe (Rust egui/wgpu desktop app) + ClipForge.exe standalone backend

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8F4B9A2E-6C3D-4E7A-9B1F-3C2D1E5A8B7C}
AppName=ClipForge
AppVersion={#AppVersion}
AppVerName=ClipForge {#AppVersion}
AppPublisher=Zykoraa
AppPublisherURL=https://github.com/Zykoraa/clipforge
AppSupportURL=https://github.com/Zykoraa/clipforge/issues
DefaultDirName={localappdata}\Programs\ClipForge
DefaultGroupName=ClipForge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=ClipForge-Setup-windows-x86_64
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\ClipForgeNative.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ClipForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ClipForge"; Filename: "{app}\ClipForgeNative.exe"; WorkingDir: "{app}"; Comment: "ClipForge — Native GPU AI Video Editor & Offline Media Studio"
Name: "{autodesktop}\ClipForge"; Filename: "{app}\ClipForgeNative.exe"; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "ClipForge — Native GPU AI Video Editor & Offline Media Studio"

[Run]
Filename: "{app}\ClipForgeNative.exe"; Description: "Launch ClipForge"; Flags: nowait postinstall skipifsilent
