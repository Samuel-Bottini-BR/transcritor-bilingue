; Instalador do Transcritor Bilingue (Inno Setup)
; Instalacao por usuario (sem UAC/admin), com atalho no menu iniciar.

#define MyAppName "Transcritor Bilingue"
#define MyAppVersion "1.1"
#define MyAppExeName "TranscritorBilingue.exe"

[Setup]
AppId={{7C4D2E1A-9B3F-4E77-A1C2-TRANSCRITORBIL}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Artesacra
DefaultDirName={autopf}\TranscritorBilingue
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; instala por usuario, sem exigir administrador
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=TranscritorBilingue-Instalador
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
; o app e 64 bits
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Area de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
; le direto da pasta que o PyInstaller acabou de gerar. Antes isso apontava
; para release\, que era uma copia manual - quem rodasse so os dois comandos do
; README empacotava a build ANTERIOR sem perceber.
Source: "dist\TranscritorBilingue\*"; DestDir: "{app}"; Excludes: "modelos\*"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o {#MyAppName} agora"; Flags: nowait postinstall skipifsilent
