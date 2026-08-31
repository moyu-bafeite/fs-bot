"""实时回购报告操作（market_data.hkex_repurchase_realtime_reports）。"""

from __future__ import annotations

from typing import Any

from lib.db.client import _md_client


def get_realtime_report_keys(trade_dates: list[str]) -> set[tuple[str, str, int, float]]:
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
    if not records:
        return 0
    resp = (
        _md_client.table("hkex_repurchase_realtime_reports")
        .insert(records)
        .execute()
    )
    return len(resp.data or [])


def get_repurchase_realtime_reports_by_trade_date(trade_date: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _md_client.table("hkex_repurchase_realtime_reports")
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


def get_realtime_reports_by_stock(
    stock_code: str, trade_date: str
) -> list[dict[str, Any]]:
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


def get_realtime_reports_by_stock_range(
    stock_code: str, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _md_client.table("hkex_repurchase_reports")
            .select("*")
            .eq("stock_code", stock_code)
            .gte("trade_date", start_date)
            .lte("trade_date", end_date)
            .order("trade_date")
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
    if not ids:
        return 0
    resp = (
        _md_client.table("hkex_repurchase_realtime_reports")
        .update({"notified": True})
        .in_("id", ids)
        .execute()
    )
    return len(resp.data or [])
