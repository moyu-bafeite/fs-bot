"""从 DB 获取原始数据。"""

from __future__ import annotations

from datetime import date
from typing import Any

from lib.db import get_stock_names
from lib.db.daily_prices import get_daily_prices_by_range
from lib.db.repurchase_realtime import get_realtime_reports_by_stock_range


def fetch_repurchase(
    stock_code: str, start: date, end: date
) -> list[dict[str, Any]]:
    """获取指定股票在日期区间内的回购记录。"""
    return get_realtime_reports_by_stock_range(
        stock_code, start.isoformat(), end.isoformat()
    )


def fetch_nr_prices(
    stock_code: str, start: date, end: date
) -> list[dict[str, Any]]:
    """获取不复权日K线数据。"""
    return get_daily_prices_by_range(
        "hk_nr_daily_prices", stock_code, start.isoformat(), end.isoformat()
    )


def fetch_br_prices(
    stock_code: str, start: date, end: date
) -> list[dict[str, Any]]:
    """获取前复权日K线数据。"""
    return get_daily_prices_by_range(
        "hk_br_daily_prices", stock_code, start.isoformat(), end.isoformat()
    )


def fetch_stock_name(stock_code: str) -> dict[str, str]:
    """获取股票名称。"""
    names = get_stock_names([stock_code])
    return names.get(stock_code, {"en": "", "zh-CN": "", "zh-HK": ""})
