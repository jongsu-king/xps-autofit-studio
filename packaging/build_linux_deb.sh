#!/usr/bin/env bash
# Build a .deb and a .tar.gz from dist/XPS AutoFit Studio (run after pyinstaller).
#   packaging/build_linux_deb.sh <version> <output-dir>
set -euo pipefail
VERSION="${1:?version}"
OUT="${2:?output dir}"
SRC="dist/XPS AutoFit Studio"
PKG="xps-autofit-studio"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
test -d "$SRC" || { echo "missing $SRC"; exit 1; }
mkdir -p "$OUT"

# ---- tar.gz (portable folder)
TARNAME="XPS-AutoFit-Studio-${VERSION}-Linux-$(uname -m)"
STAGE_TAR="$(mktemp -d)"
cp -R "$SRC" "$STAGE_TAR/$TARNAME"
cat > "$STAGE_TAR/$TARNAME/README.txt" <<EOF
XPS AutoFit Studio ${VERSION} (portable)
Run "./XPS AutoFit Studio" for the desktop application or "./xps-autofit --help"
for the command line. Needs the Qt runtime libraries: libxcb-cursor0 libegl1
libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1 (Debian/Ubuntu names).
EOF
tar -C "$STAGE_TAR" -czf "$OUT/$TARNAME.tar.gz" "$TARNAME"
rm -rf "$STAGE_TAR"

# ---- deb
ROOT="$(mktemp -d)"
INSTALL="$ROOT/opt/$PKG"
mkdir -p "$ROOT/DEBIAN" "$ROOT/opt" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/icons/hicolor/256x256/apps" "$ROOT/usr/share/doc/$PKG"
cp -R "$SRC" "$INSTALL"
ln -s "/opt/$PKG/xps-autofit" "$ROOT/usr/bin/xps-autofit"
ln -s "/opt/$PKG/XPS AutoFit Studio" "$ROOT/usr/bin/xps-autofit-studio"
cp packaging/icon_256.png "$ROOT/usr/share/icons/hicolor/256x256/apps/$PKG.png"
cp LICENSE "$ROOT/usr/share/doc/$PKG/copyright"
cat > "$ROOT/usr/share/applications/$PKG.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=XPS AutoFit Studio
Comment=Automated, reproducible XPS peak fitting
Exec="/opt/$PKG/XPS AutoFit Studio" %F
Icon=$PKG
Terminal=false
Categories=Science;Education;
MimeType=text/csv;text/plain;
EOF
INSTALLED_KB=$(du -sk "$ROOT/opt" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: science
Priority: optional
Architecture: $ARCH
Installed-Size: $INSTALLED_KB
Depends: libxcb-cursor0, libegl1, libgl1, libxkbcommon0, libdbus-1-3, libfontconfig1, libglib2.0-0t64 | libglib2.0-0
Maintainer: jongsu-king <313024960+jongsu-king@users.noreply.github.com>
Homepage: https://github.com/jongsu-king/xps-autofit-studio
Description: Automated, reproducible XPS peak fitting
 Desktop application and command-line tool for X-ray photoelectron
 spectroscopy: Shirley/Tougaard backgrounds, Voigt peaks with spin-orbit
 constraints, statistical model selection with physical checks, batch
 processing and reproducible project files.
EOF
chmod 755 "$ROOT/DEBIAN"
DEB="$OUT/${PKG}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$DEB"
rm -rf "$ROOT"
dpkg-deb --info "$DEB" | head -12
sha256sum "$OUT/$TARNAME.tar.gz" "$DEB" | tee "$OUT/linux.sha256"
