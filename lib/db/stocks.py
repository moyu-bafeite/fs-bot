"""港股股票元数据操作（meta_data.sehk_active_stocks）。"""

from __future__ import annotations

from typing import Any

from lib.db.client import _meta_client

HK_STOCKS_TABLE = "sehk_active_stocks"


def _table(name: str):
    return _meta_client.table(name)


def upsert_stocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []
    resp = _table(HK_STOCKS_TABLE).upsert(records, on_conflict="stock_code").execute()
    return resp.data


def get_hk_stocks() -> list[dict[str, Any]]:
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
    resp = (
        _table(HK_STOCKS_TABLE)
        .select("stock_code,stock_name")
        .eq("stock_code", stock_code)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_stock_names(stock_codes: list[str]) -> dict[str, dict[str, str]]:
    if not stock_codes:
        return {}
    resp = (
        _table(HK_STOCKS_TABLE)
        .select("stock_code,stock_name")
        .in_("stock_code", stock_codes)
        .execute()
    )
    return {row["stock_code"]: row["stock_name"] for row in (resp.data or [])}
