"""Supabase Postgres 操作：meta_data / market_data。"""

from __future__ import annotations

import functools
import os
import time
from typing import Any

from supabase import ClientOptions, create_client

_url = os.environ["SUPABASE_URL"]
_key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
_meta_client = create_client(_url, _key, ClientOptions(schema="meta_data"))
_md_client = create_client(_url, _key, ClientOptions(schema="market_data"))

HK_STOCKS_TABLE = "sehk_active_stocks"


def _retry(max_attempts: int = 3, backoff: float = 1.0):
    """指数退避重试装饰器，处理网络断连和 Cloudflare 限流。"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(backoff * (2**attempt))
            return func(*args, **kwargs)

        return wrapper

    return decorator


def _table(name: str):
    return _meta_client.table(name)


def upsert_stocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量 upsert 股票记录，基于 stock_code 去重。"""
    if not records:
        return []
    resp = _table(HK_STOCKS_TABLE).upsert(records, on_conflict="stock_code").execute()
    return resp.data


# ── 港股回购操作 ──


def get_hk_stocks() -> list[dict[str, Any]]:
    """分页读取 sehk_active_stocks 全部记录。"""
    stocks: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _table(HK_STOCKS_TABLE)
            .select("stock_code,stock_name")
            .order("stock_code")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            break
        stocks.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return stocks


def get_hk_stock_by_code(stock_code: str) -> dict[str, Any] | None:
    """查询单只港股（meta_data.sehk_active_stocks）。"""
    resp = (
        _table(HK_STOCKS_TABLE)
        .select("stock_code,stock_name")
        .eq("stock_code", stock_code)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_stock_names(stock_codes: list[str]) -> dict[str, dict[str, str]]:
    """批量查询股票名称，返回 {stock_code: {"en": "", "zh-CN": "", "zh-HK": ""}} 映射。"""
    if not stock_codes:
        return {}
    resp = (
        _table(HK_STOCKS_TABLE)
        .select("stock_code,stock_name")
        .in_("stock_code", stock_codes)
        .execute()
    )
    return {row["stock_code"]: row["stock_name"] for row in (resp.data or [])}


def get_hkex_repurchase_reports(trade_date: str) -> list[dict[str, Any]]:
    """分页查询指定交易日的港交所回购报告。"""
    records: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _md_client.table("hkex_repurchase_reports")
            .select("*")
            .eq("trade_date", trade_date)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            break
        records.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return records


def upsert_repurchase_reports(records: list[dict[str, Any]]) -> int:
    """批量 upsert 港交所回购报告。"""
    if not records:
        return 0
    resp = (
        _md_client.table("hkex_repurchase_reports")
        .upsert(
            records,
            on_conflict="report_date,stock_code,sec_type,trade_date,quantity,amount",
        )
        .execute()
    )
    return len(resp.data or [])


# ── 日K线数据操作 ──


def upsert_br_daily_prices(records: list[dict[str, Any]]) -> int:
    """批量 upsert 前复权日K数据。"""
    if not records:
        return 0
    resp = (
        _md_client.table("hk_br_daily_prices")
        .upsert(records, on_conflict="stock_code,trade_date")
        .execute()
    )
    return len(resp.data or [])


def upsert_nr_daily_prices(records: list[dict[str, Any]]) -> int:
    """批量 upsert 不复权日K数据。"""
    if not records:
        return 0
    resp = (
        _md_client.table("hk_nr_daily_prices")
        .upsert(records, on_conflict="stock_code,trade_date")
        .execute()
    )
    return len(resp.data or [])


# ── 回购公告链接操作 ──


def upsert_repurchase_announcements(records: list[dict[str, Any]]) -> int:
    """批量 upsert 回购公告链接。"""
    if not records:
        return 0
    resp = (
        _md_client.table("hkex_repurchase_announcements")
        .upsert(
            records,
            on_conflict="stock_code,release_time,document_url",
        )
        .execute()
    )
    return len(resp.data or [])


def get_unparsed_announcements() -> list[dict[str, Any]]:
    """获取所有未解析的回购公告链接。"""
    resp = (
        _md_client.table("hkex_repurchase_announcements")
        .select("stock_code,release_time,document_url")
        .eq("parsed", False)
        .order("release_time")
        .execute()
    )
    return resp.data or []


def mark_announcement_parsed(
    stock_code: str, release_time: str, document_url: str
) -> None:
    """标记公告为已解析。"""
    (
        _md_client.table("hkex_repurchase_announcements")
        .update({"parsed": True})
        .eq("stock_code", stock_code)
        .eq("release_time", release_time)
        .eq("document_url", document_url)
        .execute()
    )