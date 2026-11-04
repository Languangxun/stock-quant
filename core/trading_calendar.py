#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 股节假日/周末判断规则。

用于 K 线缺口过滤：如果一个缺口区间全部由周末或下列节假日窗口组成，
则视为休市缺口，不再走网络补数。

节假日窗口：
    - 星期六、星期日
    - 12 月 31 日 ~ 1 月 4 日
    - 农历 12 月 28 日 ~ 1 月 8 日
    - 4 月 4 日 ~ 4 月 7 日
    - 4 月 30 日 ~ 5 月 6 日
    - 农历 5 月 4 日 ~ 5 月 6 日
    - 农历 8 月 14 日 ~ 8 月 17 日
    - 9 月 30 日 ~ 10 月 8 日
"""

from datetime import date, datetime, timedelta

try:
    from lunardate import LunarDate
except ImportError:  # pragma: no cover - 依赖缺失时仅使用公历规则
    LunarDate = None


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def _in_gregorian_window(d: date) -> bool:
    md = (d.month, d.day)
    if md >= (12, 31) or md <= (1, 4):
        return True
    if (4, 4) <= md <= (4, 7):
        return True
    if (4, 30) <= md <= (5, 6):
        return True
    if (9, 30) <= md <= (10, 8):
        return True
    return False


def _in_lunar_window(d: date) -> bool:
    if LunarDate is None:
        return False
    try:
        lunar = LunarDate.from_solar_date(d.year, d.month, d.day)
    except Exception:
        return False
    month, day = lunar.month, lunar.day
    if (month == 12 and day >= 28) or (month == 1 and day <= 8):
        return True
    if month == 5 and 4 <= day <= 6:
        return True
    if month == 8 and 14 <= day <= 17:
        return True
    return False


def is_ignored_holiday_date(value) -> bool:
    """判断某日是否为需要忽略的周末/节假日。"""
    d = _as_date(value)
    if d.weekday() >= 5:
        return True
    return _in_gregorian_window(d) or _in_lunar_window(d)


def is_ignored_gap_range(start, end) -> bool:
    """缺口区间内所有日期都属于周末/节假日时返回 True。"""
    start = _as_date(start)
    end = _as_date(end)
    if start > end:
        return True
    current = start
    step = timedelta(days=1)
    while current <= end:
        if not is_ignored_holiday_date(current):
            return False
        current += step
    return True
