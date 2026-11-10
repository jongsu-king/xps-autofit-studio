# Installers

Every tagged release carries ready-to-run builds made by the `Installers` GitHub
Actions workflow (`.github/workflows/installers.yml`). They bundle Python, Qt and
the engine; nothing else needs to be installed.

| Platform | File | Install |
|---|---|---|
| Windows 10/11 x64 | `XPS-AutoFit-Studio-<version>-Windows-x64-Setup.exe` | Run the installer. Start-menu entry "XPS AutoFit Studio"; optional desktop icon and "add xps-autofit to PATH" |
| Windows (portable) | `XPS-AutoFit-Studio-<version>-Windows-x64.zip` | Unzip anywhere, run `XPS AutoFit Studio.exe` or `xps-autofit.exe` |
| macOS 12+ (Apple silicon) | `XPS-AutoFit-Studio-<version>-macOS-arm64.dmg` | Open the DMG and drag the app to Applications |
| macOS 12+ (Intel) | `XPS-AutoFit-Studio-<version>-macOS-x86_64.dmg` | Same, for Macs with an Intel processor (from 0.6.0) |
| Debian / Ubuntu x64 | `xps-autofit-studio_<version>_amd64.deb` | `sudo apt install ./xps-autofit-studio_<version>_amd64.deb` - installs `/opt/xps-autofit-studio`, the commands `xps-autofit-studio` and `xps-autofit`, and a desktop entry |
| Linux (portable) | `XPS-AutoFit-Studio-<version>-Linux-x86_64.tar.gz` | Extract and run `./XPS AutoFit Studio` or `./xps-autofit` |

`SHA256SUMS.txt` on the release page lists the checksums of all files.

## Updating

The desktop application checks the GitHub Releases API once a day (when *Help >
Check for updates at startup* is on; one anonymous request, the User-Agent carries
only the version).

**Automatic installation** (*Help > Install updates automatically*, on by default;
from 0.6.0). In a copy installed from one of the release files,
a newer release is downloaded in the background, its SHA-256 is compared with the
release's `SHA256SUMS.txt` (a mismatch deletes the file and nothing is installed),
and it is installed when you close the program - or at once if you answer *Yes* to
*Restart now?*. How it is applied:

| Installed from | Update |
|---|---|
| Windows setup | the new setup runs silently (`/VERYSILENT`) into the same folder; the program restarts if you chose *Restart now* |
| Windows zip | the program folder is replaced after the program exits (the folder must be writable) |
| macOS DMG | the new app is copied next to the old one and swapped in after exit (keep the app in a writable folder such as Applications; a copy started from the DMG or Downloads can only show the notice) |
| Linux tar.gz | the extracted folder is replaced after exit |
| Linux .deb | `pkexec apt-get install` asks for your password once and upgrades the package |
| pip / source | nothing is changed; the notice shows `pip install -U "xps-autofit[gui]"` |

With the option off, the newer version is shown as a link in the status bar and
*Help > Check for updates…* offers *Download* (opens the installer for your system),
*Skip this version* or *Later*; install it over the existing version.

Command line: `xps-autofit update-check` reports, `xps-autofit update-check --install`
downloads, verifies and installs (installed copies). `XPS_AUTOFIT_NO_UPDATE_CHECK=1`
turns the automatic check off. A log of every applied update is written to
`update.log` in `%APPDATA%\XPS AutoFit Studio`, `~/Library/Application Support/XPS AutoFit Studio`
or `~/.config/XPS AutoFit Studio`.

## Unsigned builds

The builds are **not code-signed**:

- **Windows** SmartScreen may show "Windows protected your PC": click *More info*
  -> *Run anyway*.
- **macOS** Gatekeeper refuses on first start ("cannot be opened because the
  developer cannot be verified"): right-click the app, choose *Open*, then *Open*
  again - or run once in Terminal
  `xattr -dr com.apple.quarantine "/Applications/XPS AutoFit Studio.app"`.
  Intel Macs are not covered by the DMG; use `pip install "xps-autofit[gui]"` there.
- **Linux** `.deb` depends on the Qt runtime libraries (`libxcb-cursor0`, `libegl1`,
  `libgl1`, `libxkbcommon0`, `libdbus-1-3`, `libfontconfig1`), which `apt` installs.

## What the workflow checks before publishing

On each platform the frozen build is exercised before it is packaged: `xps-autofit
--version`, `synth`, a recipe `fit` with CSV/JSON/PNG output and `verify` of the
project file, then the desktop app is started headless (`XPS_AUTOFIT_SMOKE=1`,
`QT_QPA_PLATFORM=offscreen`) and must exit cleanly. The Windows installer is then
installed silently, its command-line tool run and uninstalled; the `.deb` is
installed with `apt`, run and removed; the DMG is mounted and its command-line tool
run. Only then are the files uploaded.

## Building locally

```bash
pip install -e ".[gui]" pyinstaller
python packaging/make_icon.py                 # regenerates packaging/icon.*
pyinstaller packaging/xps_autofit.spec --noconfirm
# macOS:   packaging/build_mac_dmg.sh 0.2.0 installers
# Linux:   packaging/build_linux_deb.sh 0.2.0 installers
# Windows: iscc /DMyAppVersion=0.2.0 "/DSourceDir=%CD%\dist\XPS AutoFit Studio" "/DOutputDir=%CD%\installers" packaging\windows_installer.iss
```

The result is a folder (`dist/XPS AutoFit Studio`, about 230 MB; an `.app` on
macOS) with two executables that share one runtime: `XPS AutoFit Studio` (desktop)
and `xps-autofit` (command line). The launchers set `MPLCONFIGDIR` to a per-user
cache folder so Matplotlib's font cache is built once, not on every start.
