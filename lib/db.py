"""Supabase Postgres 操作：sehk_active_stocks、us_active_stocks。"""

from __future__ import annotations

import os
from typing import Any

from supabase import ClientOptions, create_client

_url = os.environ["SUPABASE_URL"]
_key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
_client = create_client(_url, _key, ClientOptions(schema="meta_data"))

STOCKS_TABLE = "sehk_active_stocks"
US_STOCKS_TABLE = "us_active_stocks"


def _table(name: str):
    return _client.table(name)


def upsert_stocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量 upsert 股票记录，基于 stock_code 去重。"""
    if not records:
        return []
    resp = _table(STOCKS_TABLE).upsert(records, on_conflict="stock_code").execute()
    return resp.data


def upsert_us_stocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量 upsert 美股记录，基于 ticker 去重。"""
    if not records:
        return []
    resp = _table(US_STOCKS_TABLE).upsert(records, on_conflict="ticker").execute()
    return resp.data


def get_existing_us_tickers() -> set[str]:
    """获取 us_active_stocks 中已有的 ticker 集合。"""
    all_tickers: set[str] = set()
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _table(US_STOCKS_TABLE)
            .select("ticker")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        all_tickers.update(row["ticker"] for row in resp.data)
        if len(resp.data) < page_size:
            break
        offset += page_size
    return all_tickers


def update_us_stock_profile(
    ticker: str,
    sector: str | None,
    fiscal_month: int,
    fiscal_day: int,
) -> None:
    """更新单条美股的 sector/fiscal_month/fiscal_day。"""
    _table(US_STOCKS_TABLE).update(
        {"sector": sector, "fiscal_month": fiscal_month, "fiscal_day": fiscal_day}
    ).eq("ticker", ticker).execute()
