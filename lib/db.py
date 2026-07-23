"""Supabase Postgres 操作：filings、sehk_active_stocks、filing_logs。"""

from __future__ import annotations

import os
from typing import Any

from supabase import ClientOptions, create_client

_url = os.environ["SUPABASE_URL"]
_key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
_client = create_client(_url, _key, ClientOptions(schema="meta_data"))

FILINGS_TABLE = "filings"
STOCKS_TABLE = "sehk_active_stocks"
LOG_TABLE = "filing_logs"


def _table(name: str):
    return _client.table(name)


def upsert_filings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量 upsert filings 记录，基于 news_id 去重。返回插入/更新的记录。"""
    if not records:
        return []
    resp = _table(FILINGS_TABLE).upsert(records, on_conflict="news_id").execute()
    return resp.data


def get_pending_filings(
    stock_code: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """查询 status='pending' 的记录。"""
    query = _table(FILINGS_TABLE).select("*").eq("status", "pending").limit(limit)
    if stock_code:
        query = query.eq("stock_code", stock_code)
    resp = query.execute()
    return resp.data


def update_filing_status(
    filing_id: int,
    status: str,
    pdf_path: str | None = None,
) -> dict[str, Any] | None:
    """更新单条 filing 的状态和 pdf_path。"""
    data: dict[str, Any] = {"status": status}
    if pdf_path is not None:
        data["pdf_path"] = pdf_path
    resp = _table(FILINGS_TABLE).update(data).eq("id", filing_id).execute()
    return resp.data[0] if resp.data else None


def log_error(
    action: str,
    message: str,
    *,
    filing_id: int | None = None,
    stock_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """写入一条错误日志到 filing_logs。"""
    record: dict[str, Any] = {
        "action": action,
        "message": message,
        "level": "error",
    }
    if filing_id is not None:
        record["filing_id"] = filing_id
    if stock_code is not None:
        record["stock_code"] = stock_code
    if details is not None:
        record["details"] = details
    _table(LOG_TABLE).insert(record).execute()


def upsert_stocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量 upsert 股票记录，基于 stock_code 去重。"""
    if not records:
        return []
    resp = _table(STOCKS_TABLE).upsert(records, on_conflict="stock_code").execute()
    return resp.data


def get_stock_id_map_from_db() -> dict[str, int]:
    """从 DB 读取 stock_code → hkex_id 映射。"""
    resp = _table(STOCKS_TABLE).select("stock_code, hkex_id").execute()
    return {row["stock_code"]: row["hkex_id"] for row in resp.data}
