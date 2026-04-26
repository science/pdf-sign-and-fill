#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$PROJECT_DIR/build"
APP_NAME="pdf-sign-and-fill"
BIN_DIR="$HOME/.local/bin"
ICON_DIR="$HOME/.local/share/icons"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "=== Installing $APP_NAME ==="

# Clean up legacy "pdf-simple-signing" install if present
for legacy in pdf-simple-signing; do
    rm -f "$BIN_DIR/$legacy" \
          "$DESKTOP_DIR/$legacy.desktop" \
          "$ICON_DIR/$legacy.svg"
done

# Create build directory with venv
echo "Creating virtual environment..."
rm -rf "$BUILD_DIR"
python3 -m venv "$BUILD_DIR/venv"
"$BUILD_DIR/venv/bin/pip" install --upgrade pip -q
"$BUILD_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q

# Copy application files into build
echo "Copying application files..."
cp -r "$PROJECT_DIR/pdfsign" "$BUILD_DIR/pdfsign"
cp "$PROJECT_DIR/gui.py" "$BUILD_DIR/gui.py"

# Create launcher script
cat > "$BUILD_DIR/$APP_NAME" << 'LAUNCHER'
#!/usr/bin/env bash
# Resolve symlinks to find the real script location
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
exec "$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/gui.py" "$@"
LAUNCHER
chmod +x "$BUILD_DIR/$APP_NAME"

# Symlink into ~/.local/bin
mkdir -p "$BIN_DIR"
ln -sf "$BUILD_DIR/$APP_NAME" "$BIN_DIR/$APP_NAME"
echo "Linked $BIN_DIR/$APP_NAME"

# Install icon
mkdir -p "$ICON_DIR"
cp "$PROJECT_DIR/assets/icon.svg" "$ICON_DIR/$APP_NAME.svg"
echo "Installed icon to $ICON_DIR/$APP_NAME.svg"

# Install desktop entry
mkdir -p "$DESKTOP_DIR"
cp "$PROJECT_DIR/$APP_NAME.desktop" "$DESKTOP_DIR/$APP_NAME.desktop"
echo "Installed desktop entry to $DESKTOP_DIR/$APP_NAME.desktop"

# Update desktop database if available
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo ""
echo "=== Installed successfully ==="
echo "Run from terminal:  $APP_NAME"
echo "Or find 'PDF Sign & Fill' in your application menu (Office category)"
