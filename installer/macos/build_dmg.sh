#!/usr/bin/env bash
# Build macOS DMG from PyInstaller output.
# This script is run by GitHub Actions on macOS runners.
#
# Prerequisites:
#   - PyInstaller has already run and produced dist/tw-patcher/ and dist/TW Mod Patcher.app
#   - create-dmg is installed (brew install create-dmg)
#   - Icon at icons/icon.icns exists (or icons/icon.png as fallback)
#
# Usage: ./installer/macos/build_dmg.sh <version>

set -euo pipefail

VERSION="${1:?Usage: build_dmg.sh <version>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
APP_NAME="TW Mod Patcher.app"
DMG_NAME="tw-patcher-${VERSION}-macos.dmg"
VOLUME_NAME="TW Mod Patcher ${VERSION}"

echo "=== Building macOS DMG ==="
echo "Version: $VERSION"
echo "App: $DIST_DIR/$APP_NAME"

# Verify the .app bundle exists
if [ ! -d "$DIST_DIR/$APP_NAME" ]; then
    echo "ERROR: $DIST_DIR/$APP_NAME not found. Run PyInstaller first."
    exit 1
fi

# Create a staging directory
STAGING_DIR="$DIST_DIR/dmg-staging"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

# Copy .app bundle to staging
cp -R "$DIST_DIR/$APP_NAME" "$STAGING_DIR/"

# Create a symlink to /Applications for drag-and-drop install
ln -s /Applications "$STAGING_DIR/Applications"

# Also include the CLI binary for direct terminal use
# Users can symlink this to /usr/local/bin themselves, or we provide a helper script
cat > "$STAGING_DIR/install-cli.sh" << 'EOF'
#!/bin/bash
# Install tw-patcher CLI to /usr/local/bin
CLI_PATH="/Applications/TW Mod Patcher.app/Contents/MacOS/tw-patcher"
LINK_PATH="/usr/local/bin/tw-patcher"

if [ ! -f "$CLI_PATH" ]; then
    echo "Error: TW Mod Patcher.app not found in /Applications"
    echo "Please drag the app to /Applications first."
    exit 1
fi

echo "Creating symlink: $LINK_PATH -> $CLI_PATH"
sudo ln -sf "$CLI_PATH" "$LINK_PATH"
echo "Done! You can now use 'tw-patcher' from the terminal."
EOF
chmod +x "$STAGING_DIR/install-cli.sh"

# Build DMG
if command -v create-dmg &> /dev/null; then
    create-dmg \
        --volname "$VOLUME_NAME" \
        --volicon "$PROJECT_ROOT/icons/icon.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 80 \
        --icon "$APP_NAME" 150 180 \
        --icon "Applications" 450 180 \
        --icon "install-cli.sh" 300 320 \
        --hide-extension "$APP_NAME" \
        --app-drop-link 450 180 \
        "$DIST_DIR/$DMG_NAME" \
        "$STAGING_DIR"
else
    # Fallback: use hdiutil directly
    echo "create-dmg not found, using hdiutil..."
    hdiutil create \
        -volname "$VOLUME_NAME" \
        -srcfolder "$STAGING_DIR" \
        -ov \
        -format UDZO \
        "$DIST_DIR/$DMG_NAME"
fi

# Clean up staging
rm -rf "$STAGING_DIR"

echo "=== DMG created: $DIST_DIR/$DMG_NAME ==="
