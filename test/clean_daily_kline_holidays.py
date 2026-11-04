#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理 daily_kline 中节假日/周末脏数据。

判断方式：
    1. 用一只高流动性基准股票（默认 601398）的 raw 日线作为交易日历；
    2. 不在基准交易日历中的日期，且满足周末/节假日规则，才视为脏数据；
    3. 可选同时重算受影响日期的 market_breadth。

用法：
    python3 test/clean_daily_kline_holidays.py             # 预览
    python3 test/clean_daily_kline_holidays.py --apply     # 删除
    python3 test/clean_daily_kline_holidays.py --apply \\
        --benchmark 601398 --start 20190101 --end 20261231
"""

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from core.db import get_connection, get_write_connection
from core.trading_calendar import is_ignored_holiday_date


def _read_benchmark_dates(cur, code, start, end):
    sql = """
        SELECT DISTINCT trade_date
        FROM daily_kline
        WHERE code = %s AND asset_type = 'stock' AND adjust_type = 'raw'
    """
    params = [code]
    if start:
        sql += " AND trade_date >= %s"
        params.append(start)
    if end:
        sql += " AND trade_date <= %s"
        params.append(end)
    sql += " ORDER BY trade_date"
    cur.execute(sql, tuple(params))
    return {r[0] for r in cur.fetchall()}


def _read_daily_counts(cur, start, end):
    sql = "SELECT trade_date, COUNT(*) FROM daily_kline WHERE 1=1"
    params = []
    if start:
        sql += " AND trade_date >= %s"
        params.append(start)
    if end:
        sql += " AND trade_date <= %s"
        params.append(end)
    sql += " GROUP BY trade_date ORDER BY trade_date"
    cur.execute(sql, tuple(params))
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description='清理 daily_kline 节假日/周末脏数据')
    parser.add_argument('--benchmark', default='601398',
                        help='基准股票代码（默认 601398）')
    parser.add_argument('--start', default=None, help='开始日期 YYYY-MM-DD')
    parser.add_argument('--end', default=None, help='结束日期 YYYY-MM-DD')
    parser.add_argument('--apply', action='store_true', help='实际删除')
    parser.add_argument('--skip-breadth', action='store_true',
                        help='不重算 market_breadth')
    args = parser.parse_args()

    with get_connection(force=True) as conn:
        if conn is None:
            raise RuntimeError('数据库不可用')
        cur = conn.cursor()
        benchmark_dates = _read_benchmark_dates(
            cur, args.benchmark, args.start, args.end)
        if not benchmark_dates:
            raise RuntimeError(
                f'基准股票 {args.benchmark} 在指定区间没有 raw 日线数据，已中止')
        daily_counts = _read_daily_counts(cur, args.start, args.end)

    candidates = []
    suspicious = []
    for trade_date, count in daily_counts:
        if trade_date in benchmark_dates:
            continue
        if is_ignored_holiday_date(trade_date):
            candidates.append((trade_date, count))
        else:
            suspicious.append((trade_date, count))

    print(f'基准股票: {args.benchmark}')
    print(f'基准交易日: {len(benchmark_dates)}')
    print(f'候选脏日期: {len(candidates)}，共 {sum(c for _, c in candidates)} 行')
    for trade_date, count in candidates:
        print(f'  {trade_date} {trade_date.strftime("%A")} {count} 行')

    if suspicious:
        print(f'\n警告: {len(suspicious)} 个非基准日期不匹配节假日规则，已跳过:')
        for trade_date, count in suspicious:
            print(f'  {trade_date} {trade_date.strftime("%A")} {count} 行')

    if not candidates:
        print('没有需要清理的数据。')
        return

    if not args.apply:
        print('\n预览模式，未删除。使用 --apply 执行清理。')
        return

    dates = [d for d, _ in candidates]
    with get_write_connection(force=True) as conn:
        if conn is None:
            raise RuntimeError('数据库不可写')
        cur = conn.cursor()
        placeholders = ', '.join(['%s'] * len(dates))
        cur.execute(
            f"DELETE FROM daily_kline WHERE trade_date IN ({placeholders})",
            tuple(dates))
        deleted = cur.rowcount

        if not args.skip_breadth:
            for trade_date in dates:
                try:
                    cur.execute(
                        "CALL recompute_market_breadth(%s, 'ALL_A')",
                        (trade_date,))
                    while cur.nextset():
                        pass
                except Exception as e:
                    print(f'  重算广度失败 {trade_date}: {e}')
            cur.execute(
                f"DELETE FROM market_breadth_dirty WHERE trade_date IN ({placeholders})",
                tuple(dates))

        conn.commit()
        print(f'已删除 daily_kline {deleted} 行，涉及 {len(dates)} 个日期。')
        print('注意: 本次只清理 daily_kline；daily_indicators 未改动。')


if __name__ == '__main__':
    main()
