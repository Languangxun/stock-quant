#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if ! venv/bin/python -c "import mplfinance" >/dev/null 2>&1; then
    echo "错误: venv 缺少 mplfinance，请先执行 venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

venv/bin/pyinstaller \
  --onefile \
  --console \
  --name squant \
  --clean \
  --noconfirm \
  --paths "$PWD" \
  --hidden-import pymysql \
  --hidden-import akshare \
  --hidden-import yfinance \
  --hidden-import lunardate \
  --collect-data akshare \
  --collect-data yfinance \
  main.py

chmod +x dist/squant
cp -f dist/squant venv/bin/squant
