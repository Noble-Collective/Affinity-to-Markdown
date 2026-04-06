; Affinity-PDF-Markdown Converter — Inno Setup Installer Script
;
; Output: Output\Affinity-PDF-Markdown-Converter_Setup.exe

[Setup]
AppName=Affinity-PDF-Markdown Converter
AppVersion=0.1.0
AppPublisher=Noble Collective
AppPublisherURL=https://github.com/Noble-Collective/Affinity-to-Markdown
DefaultDirName={commonpf}\Affinity-PDF-Markdown Converter
DefaultGroupName=Affinity-PDF-Markdown Converter
UninstallDisplayIcon={app}\Affinity-PDF-Markdown Converter.exe
OutputDir=Output
OutputBaseFilename=Affinity-PDF-Markdown-Converter_Setup
Compression=lzma2/ultra64
SolidCompression=yes
; Uncomment once you have an icon file in assets\icon.ico:
; SetupIconFile=assets\icon.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=admin
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\Affinity-PDF-Markdown Converter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Affinity-PDF-Markdown Converter"; Filename: "{app}\Affinity-PDF-Markdown Converter.exe"
Name: "{group}\Uninstall Affinity-PDF-Markdown Converter"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Affinity-PDF-Markdown Converter"; Filename: "{app}\Affinity-PDF-Markdown Converter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Affinity-PDF-Markdown Converter.exe"; Description: "Launch Affinity-PDF-Markdown Converter"; Flags: nowait postinstall skipifsilent
