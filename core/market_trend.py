#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""沪深300指数大盘趋势判断。"""

import logging
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from core.data_fetcher import DataFetcher
from core.indicators import add_all_indicators

logger = logging.getLogger(__name__)

DEFAULT_INDEX_CODE = '000852'
ADR_WINDOW = 10
ADR_BULL_THRESHOLD = 1.2
ADR_BEAR_THRESHOLD = 0.8
ADR_RANGE_UPPER = 1.2
ADR_OVERHEAT_THRESHOLD = 1.75
ADR_OVERCOLD_THRESHOLD = 0.5
BIAS20_OVERHEAT_THRESHOLD = 0.09
BIAS20_OVERCOLD_THRESHOLD = -0.09

INDEX_NAMES = {
    '000300': '沪深300',
    '000852': '中证1000',
    '000905': '中证500',
    '000016': '上证50',
    '000688': '科创50',
    '000001': '上证指数',
    '399001': '深证成指',
    '399005': '中小100',
    '399006': '创业板指',
    '000903': '中证100',
    '000922': '中证红利',
}


def get_market_trend_index():
    """从 squant.toml 读取大盘趋势指数代码，默认 000852（中证1000）。"""
    try:
        from core.config import load_config
        code = str(load_config().get('market_trend_index', DEFAULT_INDEX_CODE)).strip()
        return code or DEFAULT_INDEX_CODE
    except Exception:
        return DEFAULT_INDEX_CODE


def get_index_name(code):
    return INDEX_NAMES.get(str(code), str(code))


def _value(row, name):
    value = row.get(name)
    if value is None or pd.isna(value):
        return None
    return float(value)


def _fetch_adr_series(start_date, end_date):
    """按 ADR(N)=N日上涨家数之和/N日下跌家数之和 计算市场 ADR。"""
    try:
        from core.db import fetch_market_breadth_counts
        fetch_start = (pd.Timestamp(start_date) - timedelta(days=30)).strftime('%Y-%m-%d')
        rows = fetch_market_breadth_counts(fetch_start, end_date)
        if not rows:
            return pd.Series(dtype=float)
        bdf = pd.DataFrame(rows, columns=['trade_date', 'advance_count', 'decline_count'])
        bdf['trade_date'] = pd.to_datetime(bdf['trade_date'])
        bdf = bdf.drop_duplicates('trade_date').set_index('trade_date').sort_index()
        adv = pd.to_numeric(bdf['advance_count'], errors='coerce')
        dec = pd.to_numeric(bdf['decline_count'], errors='coerce')
        up_sum = adv.rolling(ADR_WINDOW, min_periods=ADR_WINDOW).sum()
        down_sum = dec.rolling(ADR_WINDOW, min_periods=ADR_WINDOW).sum()
        adr = up_sum / down_sum.where(down_sum > 0)
        return adr.dropna()
    except Exception as exc:
        logger.warning("获取市场ADR失败: %s", exc)
        return pd.Series(dtype=float)


def _align_adr(adr, index):
    if adr is None or len(adr) == 0:
        return pd.Series(np.nan, index=index, dtype=float)
    series = pd.to_numeric(adr, errors='coerce').sort_index()
    return series.reindex(index, method='ffill')


def classify_market_trend_series(df, adr=None):
    """逐日判断趋势，返回与 df 索引对齐的状态 Series。"""
    if df is None or len(df) == 0:
        return pd.Series(dtype=object)

    if adr is None:
        adr = _fetch_adr_series(df.index[0], df.index[-1])
    adr_series = _align_adr(adr, df.index)

    ma5 = pd.to_numeric(df.get('MA5'), errors='coerce') if 'MA5' in df.columns else None
    ma20 = pd.to_numeric(df.get('MA20'), errors='coerce') if 'MA20' in df.columns else None
    ma60 = pd.to_numeric(df.get('MA60'), errors='coerce') if 'MA60' in df.columns else None
    ma120 = pd.to_numeric(df.get('MA120'), errors='coerce') if 'MA120' in df.columns else None
    adx = pd.to_numeric(df.get('ADX14'), errors='coerce') if 'ADX14' in df.columns else None
    plus_di = pd.to_numeric(df.get('PLUS_DI'), errors='coerce') if 'PLUS_DI' in df.columns else None
    minus_di = pd.to_numeric(df.get('MINUS_DI'), errors='coerce') if 'MINUS_DI' in df.columns else None
    dif = pd.to_numeric(df.get('MACD_DIF'), errors='coerce') if 'MACD_DIF' in df.columns else None
    close = pd.to_numeric(df.get('close'), errors='coerce') if 'close' in df.columns else None
    high = pd.to_numeric(df.get('high'), errors='coerce') if 'high' in df.columns else None
    low = pd.to_numeric(df.get('low'), errors='coerce') if 'low' in df.columns else None
    if any(v is None for v in (ma5, ma20, ma60, ma120, adx, plus_di, minus_di,
                               dif, close, high, low)):
        return pd.Series('未知', index=df.index, dtype=object)

    slope = close.rolling(60).apply(
        lambda y: float(np.polyfit(np.arange(len(y)), y, 1)[0]), raw=True)
    slope20 = close.rolling(20).apply(
        lambda y: float(np.polyfit(np.arange(len(y)), y, 1)[0]), raw=True)
    mean60 = close.rolling(60).mean()
    slope_norm = slope / mean60.where(mean60 > 0)
    amplitude = high.rolling(60).max() / low.rolling(60).min().where(
        low.rolling(60).min() > 0)

    bull = (((ma5 > ma20) & (ma20 > ma60)
             & (slope20 > 0) & (dif > 0))
            | ((adx >= 25) & (plus_di > minus_di)))
    bear = (((ma5 < ma20) & (ma20 < ma60)
             & (slope20 < 0) & (dif < 0))
            | ((adx >= 25) & (plus_di < minus_di)))

    range_count = (
        (adx < 25).astype(int)
        + ((ma20 - ma60).abs() / ma60.where(ma60 != 0) < 0.03).astype(int)
        + (slope_norm.abs() < 0.001).astype(int)
        + (amplitude < 1.3).astype(int)
    )

    adr_bull = adr_series > ADR_BULL_THRESHOLD
    adr_bear = adr_series < ADR_BEAR_THRESHOLD
    adr_range = ((adr_series >= ADR_BEAR_THRESHOLD)
                 & (adr_series <= ADR_RANGE_UPPER))

    states = pd.Series('过渡', index=df.index, dtype=object)
    states[(range_count >= 2) & adr_range] = '震荡'
    states[bear | adr_bear] = '下跌'
    states[bull | adr_bull] = '上涨'

    bias20 = (close - ma20) / ma20.where(ma20 != 0)
    overheat = ((states == '上涨')
                & (adr_series > ADR_OVERHEAT_THRESHOLD)
                & (bias20 > BIAS20_OVERHEAT_THRESHOLD))
    overcold = ((states == '下跌')
                & (adr_series < ADR_OVERCOLD_THRESHOLD)
                & (bias20 < BIAS20_OVERCOLD_THRESHOLD))
    states[overheat] = '过热'
    states[overcold] = '过冷'

    valid = (ma20.notna() & ma60.notna() & ma120.notna() & adx.notna()
             & plus_di.notna() & minus_di.notna() & dif.notna()
             & slope.notna() & adr_series.notna())
    states[~valid] = '未知'
    return states


def classify_market_trend(df, adr=None):
    """根据沪深300/中证1000日线指标判断最新趋势。"""
    if df is None or len(df) < 120:
        return '未知'
    if adr is None:
        adr = _fetch_adr_series(df.index[0], df.index[-1])
    states = classify_market_trend_series(df, adr=adr)
    if states.empty:
        return '未知'
    return str(states.iloc[-1])


@lru_cache(maxsize=32)
def market_trend_states(start_date, end_date, index_code=None):
    """返回指定区间内每日大盘趋势状态 Series。"""
    code = str(index_code or get_market_trend_index()).strip() or DEFAULT_INDEX_CODE
    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date)
    fetch_start = (start_dt - timedelta(days=365)).strftime('%Y-%m-%d')
    try:
        fetcher = DataFetcher()
        df = fetcher.get_index_data(code, fetch_start, end_date)
    except Exception as exc:
        logger.warning("获取%s指数数据失败: %s", get_index_name(code), exc)
        return pd.Series(dtype=object)

    if df is None or df.empty:
        return pd.Series(dtype=object)

    df = add_all_indicators(df)
    adr = _fetch_adr_series(df.index[0], df.index[-1])
    states = classify_market_trend_series(df, adr=adr)
    return states[(states.index >= start_dt) & (states.index <= end_dt)]


@lru_cache(maxsize=16)
def analyze_market_trend(end_date=None, index_code=None):
    """获取指定指数近期日线并分析趋势，返回结果字典。"""
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    code = str(index_code or get_market_trend_index()).strip() or DEFAULT_INDEX_CODE
    index_name = get_index_name(code)
    end_dt = pd.Timestamp(end_date)
    start_date = (end_dt - timedelta(days=365)).strftime('%Y-%m-%d')

    try:
        fetcher = DataFetcher()
        df = fetcher.get_index_data(code, start_date, end_date)
    except Exception as exc:
        logger.warning("获取%s指数数据失败: %s", index_name, exc)
        return {'state': '未知', 'date': end_date, 'index_code': code,
                'index_name': index_name, 'error': str(exc)}

    if df is None or df.empty:
        return {'state': '未知', 'date': end_date, 'index_code': code,
                'index_name': index_name, 'error': f'{index_name}指数数据为空'}

    try:
        df = add_all_indicators(df)
        adr_series = _fetch_adr_series(df.index[0], df.index[-1])
        adr_aligned = _align_adr(adr_series, df.index)
        state = classify_market_trend(df, adr=adr_series)
        row = df.iloc[-1]
        adr_val = adr_aligned.iloc[-1]
        close_val = _value(row, 'close')
        ma20_val = _value(row, 'MA20')
        bias20_val = ((close_val - ma20_val) / ma20_val
                      if close_val is not None and ma20_val not in (None, 0) else None)
        return {
            'state': state,
            'date': df.index[-1].strftime('%Y-%m-%d'),
            'index_code': code,
            'index_name': index_name,
            'close': _value(row, 'close'),
            'ma20': _value(row, 'MA20'),
            'ma60': _value(row, 'MA60'),
            'ma120': _value(row, 'MA120'),
            'adx': _value(row, 'ADX14'),
            'plus_di': _value(row, 'PLUS_DI'),
            'minus_di': _value(row, 'MINUS_DI'),
            'dif': _value(row, 'MACD_DIF'),
            'adr': None if pd.isna(adr_val) else float(adr_val),
            'adr_window': ADR_WINDOW,
            'bias20': bias20_val,
            'error': None,
        }
    except Exception as exc:
        logger.warning("%s趋势计算失败: %s", index_name, exc)
        return {'state': '未知', 'date': end_date, 'index_code': code,
                'index_name': index_name, 'error': str(exc)}
