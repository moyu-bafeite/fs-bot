"""批量回购报告操作（market_data.hkex_repurchase_reports）。"""

from __future__ import annotations

from typing import Any

from lib.db.client import _md_client


def get_repurchase_reports_by_trade_date(trade_date: str) -> list[dict[str, Any]]:
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
