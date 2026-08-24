"""Supabase Postgres 操作：meta_data / market_data。"""

from __future__ import annotations

import functools
import os
import time
from collections.abc import Callable
from typing import Any

from supabase import ClientOptions, create_client

_url = os.environ["SUPABASE_URL"]
_key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
_meta_client = create_client(_url, _key, ClientOptions(schema="meta_data"))
_md_client = create_client(_url, _key, ClientOptions(schema="market_data"))

HK_STOCKS_TABLE = "sehk_active_stocks"


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


def _batch_upsert(
    table_name: str,
    records: list[dict[str, Any]],
    on_conflict: str,
    page_size: int = 1000,
    on_page: Callable[[int, int, int], None] | None = None,
) -> int:
    """分页批量 upsert，每页最多 page_size 条。

    Args:
        on_page: 每页上传后的回调，参数为 (当前页序号, 本页条数, 累计条数)
    """
    total = 0
    pages = (len(records) + page_size - 1) // page_size
    for page_idx in range(pages):
        i = page_idx * page_size
        batch = records[i : i + page_size]
        resp = (
            _md_client.table(table_name)
            .upsert(batch, on_conflict=on_conflict)
            .execute()
        )
        count = len(resp.data or [])
        total += count
        if on_page:
            on_page(page_idx + 1, count, total)
    return total


def upsert_br_daily_prices(
    records: list[dict[str, Any]],
    on_page: Callable[[int, int, int], None] | None = None,
) -> int:
    """分页批量 upsert 前复权日K数据（每页 1000 条）。"""
    return _batch_upsert("hk_br_daily_prices", records, "stock_code,trade_date", on_page=on_page)


def upsert_nr_daily_prices(
    records: list[dict[str, Any]],
    on_page: Callable[[int, int, int], None] | None = None,
) -> int:
    """分页批量 upsert 不复权日K数据（每页 1000 条）。"""
    return _batch_upsert("hk_nr_daily_prices", records, "stock_code,trade_date", on_page=on_page)


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


def get_existing_urls(target_date: str) -> set[str]:
    """获取指定日期已存在的 document_url 集合，用于增量过滤。

    target_date 格式: YYYY-MM-DD，匹配 release_time 以该日期开头的记录。
    """
    urls: set[str] = set()
    page_size = 1000
    offset = 0
    # release_time 格式为 "DD/MM/YYYY HH:MM"，用 like 匹配日期部分
    year, month, day = target_date.split("-")
    prefix = f"{day}/{month}/{year}"
    while True:
        resp = (
            _md_client.table("hkex_repurchase_announcements")
            .select("document_url")
            .like("release_time", f"{prefix}%")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        urls.update(row["document_url"] for row in rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return urls


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


# ── 实时回购报告操作 ──


def get_realtime_report_keys(trade_dates: list[str]) -> set[tuple[str, str, int, float]]:
    """获取指定交易日已有的去重键集合：(stock_code, trade_date, quantity, amount)。"""
    keys: set[tuple[str, str, int, float]] = set()
    if not trade_dates:
        return keys
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _md_client.table("hkex_repurchase_realtime_reports")
            .select("stock_code,trade_date,quantity,amount")
            .in_("trade_date", trade_dates)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        for row in rows:
            keys.add((row["stock_code"], row["trade_date"], int(row["quantity"] or 0), float(row["amount"] or 0)))
        if len(rows) < page_size:
            break
        offset += page_size
    return keys


def insert_realtime_reports(records: list[dict[str, Any]]) -> int:
    """批量插入实时回购报告。"""
    if not records:
        return 0
    resp = (
        _md_client.table("hkex_repurchase_realtime_reports")
        .insert(records)
        .execute()
    )
    return len(resp.data or [])


def get_realtime_reports_by_stock(
    stock_code: str, trade_date: str
) -> list[dict[str, Any]]:
    """查询指定股票在指定交易日的所有回购记录（可能含多币种）。"""
    records: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _md_client.table("hkex_repurchase_realtime_reports")
            .select("*")
            .eq("stock_code", stock_code)
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


def get_unnotified_realtime_reports_by_stock(
    stock_code: str, trade_date: str
) -> list[dict[str, Any]]:
    """查询指定股票在指定交易日的所有回购记录（可能含多币种）。"""
    records: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _md_client.table("hkex_repurchase_realtime_reports")
            .select("*")
            .eq("stock_code", stock_code)
            .eq("trade_date", trade_date)
            .eq("notified", False)
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


def get_latest_unnotified_realtime_report() -> dict[str, Any] | None:
    """获取最新一条未通知的实时回购报告。"""
    resp = (
        _md_client.table("hkex_repurchase_realtime_reports")
        .select("*")
        .eq("notified", False)
        .order("trade_date", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def mark_realtime_reports_notified(ids: list[int]) -> int:
    """将指定 id 的记录标记为已通知。"""
    if not ids:
        return 0
    resp = (
        _md_client.table("hkex_repurchase_realtime_reports")
        .update({"notified": True})
        .in_("id", ids)
        .execute()
    )
    return len(resp.data or [])