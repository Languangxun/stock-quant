#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

venv/bin/pyinstaller \
  --onefile \
  --console \
  --name daemon \
  --clean \
  --noconfirm \
  daemon.py

chmod +x dist/daemon
cp -f dist/daemon venv/bin/daemon
