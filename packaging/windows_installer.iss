; Inno Setup script for XPS AutoFit Studio (run after pyinstaller on Windows).
;   iscc /DMyAppVersion=0.2.0 /DSourceDir="dist\XPS AutoFit Studio" /DOutputDir=installers packaging\windows_installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\XPS AutoFit Studio"
#endif
#ifndef OutputDir
  #define OutputDir "..\installers"
#endif
#define MyAppName "XPS AutoFit Studio"
#define MyAppExe "XPS AutoFit Studio.exe"
#define MyCliExe "xps-autofit.exe"

[Setup]
AppId={{A3F1B7E2-6C4D-4F8A-9E5B-2D7C1F0A8B31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=jongsu-king
AppPublisherURL=https://github.com/jongsu-king/xps-autofit-studio
AppSupportURL=https://github.com/jongsu-king/xps-autofit-studio/issues
AppUpdatesURL=https://github.com/jongsu-king/xps-autofit-studio/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=XPS-AutoFit-Studio-{#MyAppVersion}-Windows-x64-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add the command-line tool (xps-autofit) to PATH"; GroupDescription: "Command line:"; Flags: unchecked

[InstallDelete]
; an upgrade (also the silent one started by the in-app updater) must not keep
; libraries of the previous version
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKA, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;
