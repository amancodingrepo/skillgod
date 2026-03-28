#!/bin/bash
set -e

INSTALL_DIR="/usr/local/bin"
BINARY="sg"

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case $ARCH in
  x86_64)  ARCH="amd64" ;;
  aarch64) ARCH="arm64" ;;
  arm64)   ARCH="arm64" ;;
esac

echo "Installing SkillGod..."
echo "OS: $OS  ARCH: $ARCH"

# For now copy from local build (GitHub releases added in v1.1)
if [ -f "./sg" ]; then
  cp ./sg "$INSTALL_DIR/$BINARY"
  chmod +x "$INSTALL_DIR/$BINARY"
  echo "Installed sg to $INSTALL_DIR/$BINARY"
elif [ -f "./sg.exe" ]; then
  cp ./sg.exe "$INSTALL_DIR/$BINARY"
  chmod +x "$INSTALL_DIR/$BINARY"
  echo "Installed sg to $INSTALL_DIR/$BINARY"
else
  echo "Build the binary first: cd cli && go build -o ../sg ."
  exit 1
fi

echo ""
echo "Run: sg init"
echo "Then restart your IDE."
