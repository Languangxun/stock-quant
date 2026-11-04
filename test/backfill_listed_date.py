#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填 stocks.listed_date（上市日期）。

数据来源：AkShare 的上交所/深交所/北交所股票列表。
同时为 daily_kline 中出现但 stocks 缺失的股票补建资产记录。

用法：
    python3 test/backfill_listed_date.py            # 预览
    python3 test/backfill_listed_date.py --apply    # 写入数据库
    python3 test/backfill_listed_date.py --apply --overwrite
"""

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import pandas as pd

from core.db import get_connection, get_write_connection


def _collect(frame, code_col, date_col, name_col, exchange, mapping):
    if frame is None or frame.empty:
        return
    for _, row in frame.iterrows():
        code = str(row.get(code_col, '')).strip()
        if not code or not code.isdigit():
            continue
        code = code.zfill(6)
        listed = pd.to_datetime(row.get(date_col), errors='coerce')
        if pd.isna(listed):
            continue
        mapping[code] = {
            'listed_date': listed.date(),
            'name': str(row.get(name_col, '') or '').strip() or code,
            'exchange': exchange,
        }


def fetch_listed_dates(verbose=True):
    import akshare as ak

    mapping = {}
    sources = [
        ('上交所主板', lambda: ak.stock_info_sh_name_code(symbol='主板A股'),
         '证券代码', '上市日期', '证券简称', 'SH'),
        ('上交所科创板', lambda: ak.stock_info_sh_name_code(symbol='科创板'),
         '证券代码', '上市日期', '证券简称', 'SH'),
        ('深交所', lambda: ak.stock_info_sz_name_code(),
         'A股代码', 'A股上市日期', 'A股简称', 'SZ'),
        ('北交所', lambda: ak.stock_info_bj_name_code(),
         '证券代码', '上市日期', '证券简称', 'BJ'),
    ]
    for label, func, code_col, date_col, name_col, exchange in sources:
        try:
            df = func()
            _collect(df, code_col, date_col, name_col, exchange, mapping)
            if verbose:
                print(f'  {label}: {len(df)} 条')
        except Exception as e:
            print(f'  {label}: 失败 {type(e).__name__}: {e}')
    return mapping


def main():
    parser = argparse.ArgumentParser(description='回填 stocks.listed_date')
    parser.add_argument('--apply', action='store_true', help='实际写入数据库')
    parser.add_argument('--overwrite', action='store_true',
                        help='覆盖已有 listed_date')
    args = parser.parse_args()

    print('正在获取上市日期...')
    listed_map = fetch_listed_dates()
    print(f'获取到 {len(listed_map)} 个股票上市日期')

    with get_connection(force=True) as conn:
        if conn is None:
            raise RuntimeError('数据库不可用')
        cur = conn.cursor()
        cur.execute("""
            SELECT code, exchange, asset_type, listed_date
            FROM stocks
            WHERE asset_type = 'stock'
        """)
        stock_rows = cur.fetchall()
        cur.execute("""
            SELECT DISTINCT code
            FROM daily_kline
            WHERE asset_type = 'stock'
        """)
        kline_codes = {r[0] for r in cur.fetchall()}

    existing = {row[0] for row in stock_rows}
    matched = []
    for code, exchange, asset_type, current in stock_rows:
        info = listed_map.get(code)
        if info is None:
            continue
        if current is not None and not args.overwrite:
            continue
        matched.append((info['listed_date'], code, exchange, asset_type))

    missing_codes = sorted(code for code in kline_codes if code not in existing)
    missing_inserts = []
    for code in missing_codes:
        info = listed_map.get(code)
        if info is None:
            continue
        missing_inserts.append((
            code, info['exchange'], 'stock', info['name'],
            info['exchange'].lower(), info['listed_date']))

    print(f'stocks 股票记录: {len(stock_rows)}')
    print(f'可回填 listed_date: {len(matched)}')
    print(f'daily_kline 中缺失资产记录: {len(missing_codes)}，'
          f'可补建: {len(missing_inserts)}')
    for listed, code, exchange, asset_type in matched[:8]:
        print(f'  update {code} {exchange} {asset_type} -> {listed}')
    for code, exchange, asset_type, name, market, listed in missing_inserts[:8]:
        print(f'  insert {code} {exchange} {asset_type} {name} -> {listed}')
    if len(matched) + len(missing_inserts) > 8:
        print('  ...')

    if not args.apply:
        print('预览模式，未写库。使用 --apply 写入。')
        return

    with get_write_connection(force=True) as conn:
        if conn is None:
            raise RuntimeError('数据库不可写')
        cur = conn.cursor()
        if matched:
            cur.executemany("""
                UPDATE stocks
                SET listed_date = %s
                WHERE code = %s AND exchange = %s AND asset_type = %s
            """, matched)
        if missing_inserts:
            cur.executemany("""
                INSERT INTO stocks (code, exchange, asset_type, name, market, listed_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    listed_date = VALUES(listed_date)
            """, missing_inserts)
        conn.commit()
        print(f'已回填 listed_date {len(matched)} 条，'
              f'补建股票记录 {len(missing_inserts)} 条')


if __name__ == '__main__':
    main()
