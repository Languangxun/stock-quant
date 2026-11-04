#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

venv/bin/pyinstaller \
  --onefile \
  --console \
  --name poolmgr \
  --clean \
  --noconfirm \
  poolmgr.py

chmod +x dist/poolmgr
cp -f dist/poolmgr venv/bin/poolmgr
