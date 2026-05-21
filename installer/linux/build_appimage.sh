#!/usr/bin/env bash
# Build Linux AppImage from PyInstaller output.
# This script is run by GitHub Actions on Ubuntu runners.
#
# Prerequisites:
#   - PyInstaller has already run and produced dist/tw-patcher/
#   - appimagetool is available (downloaded during CI)
#   - Icon at icons/icon.png exists
#
# Usage: ./installer/linux/build_appimage.sh <version>

set -euo pipefail

VERSION="${1:?Usage: build_appimage.sh <version>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
APPDIR="$DIST_DIR/TW-Mod-Patcher.AppDir"
APPIMAGE_NAME="tw-patcher-${VERSION}-x86_64.AppImage"

echo "=== Building Linux AppImage ==="
echo "Version: $VERSION"

# Verify PyInstaller output exists
if [ ! -d "$DIST_DIR/tw-patcher" ]; then
    echo "ERROR: $DIST_DIR/tw-patcher not found. Run PyInstaller first."
    exit 1
fi

# Create AppDir structure
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/icons/hicolor/512x512/apps"
mkdir -p "$APPDIR/usr/share/applications"

# Copy PyInstaller output
cp -R "$DIST_DIR/tw-patcher/"* "$APPDIR/usr/bin/"

# Copy icon
cp "$PROJECT_ROOT/icons/icon.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/tw-patcher.png"
cp "$PROJECT_ROOT/icons/icon.png" "$APPDIR/tw-patcher.png"

# Copy .desktop file
cp "$SCRIPT_DIR/tw-patcher.desktop" "$APPDIR/usr/share/applications/"
cp "$SCRIPT_DIR/tw-patcher.desktop" "$APPDIR/"

# Create AppRun script
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/bin:${LD_LIBRARY_PATH:-}"

# If called with no arguments or with 'ui', launch accordingly
exec "${HERE}/usr/bin/tw-patcher" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# Download appimagetool if not present
APPIMAGETOOL="$DIST_DIR/appimagetool"
if [ ! -f "$APPIMAGETOOL" ]; then
    echo "Downloading appimagetool..."
    curl -L -o "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

# Build AppImage
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$DIST_DIR/$APPIMAGE_NAME"

# Clean up
rm -rf "$APPDIR"

echo "=== AppImage created: $DIST_DIR/$APPIMAGE_NAME ==="
