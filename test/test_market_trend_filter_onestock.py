#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比“大盘下跌时禁止买入”与“不禁止买入”的单持仓回测效果。

等价命令（onestock 属于 backtest 命令）：
    backtest -sf input/pool.txt -st <start> -e <end> -g boll,macd --onestock
    backtest -sf input/pool.txt -st <start> -e <end> -g boll,macd --onestock \\
        --block-buy-on-downtrend

测试周期：2020、2021、2022、2023、2024、2025、2026。
"""

import contextlib
import io
import os
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import pandas as pd

import main

POOL_PATH = os.path.join(_ROOT, 'input', 'pool.txt')
STRATEGIES = ['boll', 'macd']
STRATEGY_ENHANCE = {'boll': 0, 'macd': 0}
CAPITAL = 1_000_000
YEARS = range(2020, 2027)


def _read_pool():
    symbols = main._read_symbols_file(POOL_PATH)
    if not symbols:
        raise RuntimeError(f'股票池为空或不存在: {POOL_PATH}')
    return symbols


def _year_range(year):
    start = f'{year}-01-01'
    end = f'{year}-12-31'
    today = datetime.now().strftime('%Y-%m-%d')
    end = min(end, today)
    return start, end


def _run_case(symbols, start_date, end_date, block, label):
    main._set_seqnum(0)
    main._set_fix_capital(False)
    main._set_max_hold_days(None)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = main._run_onestock_backtest(
            symbols,
            start_date,
            end_date,
            STRATEGIES,
            STRATEGY_ENHANCE,
            CAPITAL,
            './output',
            random_mode=False,
            random_count=100,
            fix_capital=False,
            file_part=label,
            replace_on_buy=0,
            block_buy_on_downtrend=block,
        )

    if result is None:
        raise RuntimeError(f'{label} 回测失败:\n{stdout.getvalue()}')
    return result['result']


def _pct(v):
    return f'{v * 100:.2f}%' if v is not None else 'N/A'


def main_test():
    symbols = _read_pool()
    print(f'股票池: {len(symbols)} 只')
    print(f'策略: {", ".join(STRATEGIES)}')
    print()

    rows = []
    for year in YEARS:
        start, end = _year_range(year)
        print(f'正在回测 {year}: {start} ~ {end} ...')
        base = _run_case(symbols, start, end, False, f'trend_off_{year}')
        capped = _run_case(symbols, start, end, True, f'trend_on_{year}')
        rows.append((year, start, end, base, capped))

    print()
    print('=' * 108)
    print('大盘下跌时禁止买入 vs 不禁止买入（onestock）')
    print('=' * 108)
    print(f'{"年份":<6} {"区间":<24} {"不禁止收益率":>12} {"禁止收益率":>12} {"差异":>12} '
          f'{"交易(不禁止)":>12} {"交易(禁止)":>10}')
    print('-' * 108)
    for year, start, end, base, capped in rows:
        diff = (capped.get('total_return') or 0) - (base.get('total_return') or 0)
        print(f'{year:<6} {start} ~ {end:<10} '
              f'{_pct(base.get("total_return")):>12} '
              f'{_pct(capped.get("total_return")):>12} '
              f'{diff * 100:>+10.2f}pct '
              f'{str(base.get("total_trades")):>12} '
              f'{str(capped.get("total_trades")):>10}')
    print('=' * 108)

    return rows


if __name__ == '__main__':
    main_test()
