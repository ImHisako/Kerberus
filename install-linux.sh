#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARCH="$(uname -m)"
SOURCE="$SCRIPT_DIR/Kerberus-linux-$ARCH"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/kerberus"
BIN_DIR="$HOME/.local/bin"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [[ ! -x "$SOURCE" ]]; then
  echo "Binario $SOURCE non trovato accanto all'installer." >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APPLICATIONS_DIR"
install -m 0755 "$SOURCE" "$INSTALL_DIR/Kerberus"
ln -sfn "$INSTALL_DIR/Kerberus" "$BIN_DIR/kerberus"

cat > "$APPLICATIONS_DIR/kerberus.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Kerberus
Comment=Private hybrid post-quantum messenger over I2P
Exec=$INSTALL_DIR/Kerberus
Terminal=false
Categories=Network;InstantMessaging;
StartupNotify=true
EOF

echo "Kerberus installato. Avvia dal menu applicazioni o con: $BIN_DIR/kerberus"
if ! command -v i2prouter >/dev/null 2>&1; then
  echo "Nota: installa I2P dal repository ufficiale e abilita SAM su 127.0.0.1:7656."
fi
