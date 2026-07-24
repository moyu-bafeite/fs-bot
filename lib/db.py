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
EXCLUDE_KEYWORDS_TABLE = "filing_excluded_keywords"


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
    """从 DB 读取 stock_code → hkex_id 映射（分页查询全量数据）。"""
    all_rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _table(STOCKS_TABLE)
            .select("stock_code, hkex_id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        all_rows.extend(resp.data)
        if len(resp.data) < page_size:
            break
        offset += page_size
    return {row["stock_code"]: row["hkex_id"] for row in all_rows}


def get_excluded_keywords() -> list[str]:
    """获取已启用的排除关键词列表。"""
    resp = (
        _table(EXCLUDE_KEYWORDS_TABLE).select("keyword").eq("enabled", True).execute()
    )
    return [row["keyword"] for row in resp.data]


def get_filings_by_keywords(keywords: list[str]) -> list[dict[str, Any]]:
    """查询标题匹配排除关键词的 filings 记录。"""
    if not keywords:
        return []
    all_records: list[dict[str, Any]] = []
    for kw in keywords:
        resp = (
            _table(FILINGS_TABLE)
            .select(
                "id, news_id, stock_code, title, filing_type, report_year, filing_date, file_url"
            )
            .ilike("title", f"%{kw}%")
            .execute()
        )
        all_records.extend(resp.data)
    seen: set[int] = set()
    unique: list[dict[str, Any]] = []
    for rec in all_records:
        if rec["id"] not in seen:
            seen.add(rec["id"])
            unique.append(rec)
    return unique


def delete_filings_by_ids(ids: list[int]) -> int:
    """按 ID 列表删除 filings 记录，返回删除数量。"""
    if not ids:
        return 0
    resp = _table(FILINGS_TABLE).delete().in_("id", ids).execute()
    return len(resp.data)
