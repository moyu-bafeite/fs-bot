"""日K线价格数据操作（market_data.hk_{nr,br}_daily_prices）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lib.db.client import _md_client


def _batch_upsert(
    table_name: str,
    records: list[dict[str, Any]],
    on_conflict: str,
    page_size: int = 1000,
    on_page: Callable[[int, int, int], None] | None = None,
) -> int:
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
    return _batch_upsert("hk_br_daily_prices", records, "stock_code,trade_date", on_page=on_page)


def upsert_nr_daily_prices(
    records: list[dict[str, Any]],
    on_page: Callable[[int, int, int], None] | None = None,
) -> int:
    return _batch_upsert("hk_nr_daily_prices", records, "stock_code,trade_date", on_page=on_page)


def get_nr_daily_turnover(stock_code: str, trade_date: str) -> float | None:
    resp = (
        _md_client.table("hk_nr_daily_prices")
        .select("turnover")
        .eq("stock_code", stock_code)
        .eq("trade_date", trade_date)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        return None
    turnover = rows[0].get("turnover")
    return float(turnover) if turnover is not None else None


def get_nr_daily_turnovers(trade_date: str) -> dict[str, float]:
    result: dict[str, float] = {}
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _md_client.table("hk_nr_daily_prices")
            .select("stock_code,turnover")
            .eq("trade_date", trade_date)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        for row in rows:
            turnover = row.get("turnover")
            if turnover is not None:
                result[row["stock_code"]] = float(turnover)
        if len(rows) < page_size:
            break
        offset += page_size
    return result


def get_max_trade_dates(
    table_name: str, stock_codes: list[str], max_workers: int = 8
) -> dict[str, str]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    result: dict[str, str] = {}

    def _query_one(code: str) -> tuple[str, str | None]:
        resp = (
            _md_client.table(table_name)
            .select("trade_date")
            .eq("stock_code", code)
            .order("trade_date", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return (code, rows[0]["trade_date"]) if rows else (code, None)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_query_one, code): code
            for code in stock_codes
        }
        for future in as_completed(futures):
            code, max_date = future.result()
            if max_date is not None:
                result[code] = max_date

    return result
