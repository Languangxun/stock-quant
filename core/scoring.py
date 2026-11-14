#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技术指标量化评分。

score 用于辅助分析买卖信号，不做固定范围限制。
当前由多个独立技术指标各贡献 -1/0/+1，直接累加得到整数分数。
"""

from functools import lru_cache

import pandas as pd


COMPONENT_ORDER = ('MA', 'EMA', 'DMI', 'AMT', 'OBV', 'RSI', 'WR', 'SAR', 'PE', 'KDJ')


def _num(df, col):
    if col not in df.columns:
        return None
    return pd.to_numeric(df[col], errors='coerce')


@lru_cache(maxsize=256)
def _fetch_pe_rows(symbol):
    try:
        from core.db import fetch_valuation, infer_asset_type
        asset_type = infer_asset_type(symbol)
        rows = fetch_valuation(symbol, asset_type=asset_type, force=True)
        if not rows and asset_type != 'stock':
            rows = fetch_valuation(symbol, asset_type='stock', force=True)
        return tuple(rows)
    except Exception:
        return ()


def _pe_series(df):
    if 'pe_ttm' in df.columns:
        return pd.to_numeric(df['pe_ttm'], errors='coerce')
    if 'PE' in df.columns:
        return pd.to_numeric(df['PE'], errors='coerce')

    symbol = df.attrs.get('symbol')
    if not symbol:
        return None

    rows = _fetch_pe_rows(str(symbol))
    if not rows:
        return None

    values = {
        pd.Timestamp(row[0]): row[1]
        for row in rows
        if row[1] is not None
    }
    if not values:
        return None
    series = pd.to_numeric(pd.Series(values).sort_index(), errors='coerce')
    return series.reindex(df.index, method='ffill')


def _component_frame(df):
    close = _num(df, 'close')
    ma5 = _num(df, 'MA5')
    ma10 = _num(df, 'MA10')
    ema12 = _num(df, 'EMA12')
    ema26 = _num(df, 'EMA26')
    adx = _num(df, 'ADX14')
    plus_di = _num(df, 'PLUS_DI')
    minus_di = _num(df, 'MINUS_DI')
    amount = _num(df, 'amount')
    obv = _num(df, 'OBV')
    rsi = _num(df, 'RSI14')
    wr = _num(df, 'WR14')
    sar = _num(df, 'SAR')
    kdj_k = _num(df, 'KDJ_K')
    kdj_d = _num(df, 'KDJ_D')
    kdj_j = _num(df, 'KDJ_J')
    pe = _pe_series(df)

    comp = pd.DataFrame(0, index=df.index, columns=COMPONENT_ORDER, dtype=int)

    if close is not None and ma5 is not None and ma10 is not None:
        comp['MA'] = ((close > ma5) & (ma5 > ma10)).astype(int)
        comp['MA'] -= ((close < ma5) & (ma5 < ma10)).astype(int)
    if close is not None and ema12 is not None and ema26 is not None:
        comp['EMA'] = ((close > ema12) & (ema12 > ema26)).astype(int)
        comp['EMA'] -= ((close < ema12) & (ema12 < ema26)).astype(int)

    if adx is not None and plus_di is not None and minus_di is not None:
        trend = (adx > 25) & (adx < 50)
        comp['DMI'] = (trend & (plus_di > minus_di)).astype(int)
        comp['DMI'] -= (trend & (plus_di < minus_di)).astype(int)

    if amount is not None and close is not None:
        amt_high = amount >= amount.rolling(5, min_periods=5).max()
        price_high = close >= close.rolling(5, min_periods=5).max()
        price_low = close <= close.rolling(5, min_periods=5).min()
        comp['AMT'] = (amt_high & price_high).astype(int)
        comp['AMT'] -= (amt_high & price_low).astype(int)

    if obv is not None and adx is not None and plus_di is not None and minus_di is not None:
        obv_ma20 = obv.rolling(20).mean()
        obv_above_ma20 = obv > obv_ma20
        rsi_lt30 = (rsi < 30) if rsi is not None else False
        obv_buy = (
            ((adx < 25) & rsi_lt30 & obv_above_ma20)
            | ((adx > 25) & (plus_di > minus_di) & obv_above_ma20)
        )
        obv_sell = pd.Series(False, index=df.index)
        if close is not None:
            price_ma10 = ma10 if ma10 is not None else close.rolling(10).mean()
            price_high10 = close >= close.rolling(10).max()
            obv_not_high10 = obv < obv.rolling(10).max()
            price_below_ma10 = close < price_ma10
            obv_below_ma10 = obv < obv.rolling(10).mean()
            obv_sell = (
                ((adx > 25) & price_high10 & obv_not_high10)
                | ((adx > 25) & price_below_ma10 & obv_below_ma10)
            )
        comp['OBV'] = obv_buy.astype(int) - obv_sell.astype(int)

    if rsi is not None:
        comp['RSI'] = (rsi < 30).astype(int)
        comp['RSI'] -= (rsi > 70).astype(int)

    if wr is not None:
        wr_positive = -wr
        comp['WR'] = (wr_positive > 80).astype(int)
        comp['WR'] -= (wr_positive < 20).astype(int)

    if close is not None and sar is not None:
        comp['SAR'] = (close > sar).astype(int)
        comp['SAR'] -= (close < sar).astype(int)

    if pe is not None:
        comp['PE'] = ((pe > 0) & (pe < 50)).astype(int)
        comp['PE'] -= (pe < 0).astype(int)

    kdj_buy = None
    kdj_sell = None
    if kdj_k is not None:
        kdj_buy = kdj_k < 20
    if kdj_j is not None:
        kdj_buy = kdj_j < 0 if kdj_buy is None else (kdj_buy | (kdj_j < 0))
        kdj_sell = kdj_j > 100
    if kdj_d is not None:
        kdj_sell = kdj_d > 80 if kdj_sell is None else (kdj_sell | (kdj_d > 80))
    if kdj_buy is not None:
        comp['KDJ'] += kdj_buy.astype(int)
    if kdj_sell is not None:
        comp['KDJ'] -= kdj_sell.astype(int)

    return comp


def _format_detail(values):
    positive = [name for name in COMPONENT_ORDER if values.get(name, 0) > 0]
    negative = [name for name in COMPONENT_ORDER if values.get(name, 0) < 0]
    parts = []
    if positive:
        parts.append('+' + ','.join(positive))
    if negative:
        parts.append('-' + ','.join(negative))
    return '；'.join(parts) if parts else '—'


def compute_daily_score_with_detail(df):
    """返回 (score, score_detail) 两个与 df 索引对齐的 Series。

    score: 整数评分。
    score_detail: 形如 '+MA,EMA；-KDJ' 的说明文本。
    """
    if df is None or len(df) == 0:
        return (pd.Series(dtype=int, name='score'),
                pd.Series(dtype=object, name='score_detail'))

    comp = _component_frame(df)
    score = comp.sum(axis=1).astype(int).rename('score')
    detail = comp.apply(lambda row: _format_detail(row.to_dict()), axis=1)
    detail = detail.rename('score_detail')
    return score, detail


def compute_daily_score(df):
    """计算每个交易日的综合技术评分（整数）。"""
    score, _ = compute_daily_score_with_detail(df)
    return score
