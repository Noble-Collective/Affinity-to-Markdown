; HomeStead Converter — Inno Setup Installer Script
; ──────────────────────────────────────────────────
;
; Prerequisites:
;   1. Run `build.bat` first to create the PyInstaller dist folder
;   2. Install Inno Setup from https://jrsoftware.org/isinfo.php
;   3. Open this file in Inno Setup Compiler and click Build → Compile
;      (or run: iscc installer.iss)
;
; Output: Output\HomeStead_Converter_Setup.exe

[Setup]
AppName=HomeStead Converter
AppVersion=0.1.0
AppPublisher=Noble Collective
AppPublisherURL=https://github.com/Noble-Collective/Affinity-to-Markdown
DefaultDirName={autopf}\HomeStead Converter
DefaultGroupName=HomeStead Converter
UninstallDisplayIcon={app}\HomeStead Converter.exe
OutputDir=Output
OutputBaseFilename=HomeStead_Converter_Setup
Compression=lzma2/ultra64
SolidCompression=yes
; Uncomment once you have an icon file in assets\icon.ico:
; SetupIconFile=assets\icon.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Bundle everything from the PyInstaller dist folder
Source: "dist\HomeStead Converter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut
Name: "{group}\HomeStead Converter"; Filename: "{app}\HomeStead Converter.exe"
Name: "{group}\Uninstall HomeStead Converter"; Filename: "{uninstallexe}"
; Desktop shortcut (optional, user-selected)
Name: "{autodesktop}\HomeStead Converter"; Filename: "{app}\HomeStead Converter.exe"; Tasks: desktopicon

[Run]
; Option to launch the app after install
Filename: "{app}\HomeStead Converter.exe"; Description: "Launch HomeStead Converter"; Flags: nowait postinstall skipifsilent
