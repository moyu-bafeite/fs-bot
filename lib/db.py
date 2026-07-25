"""Supabase Postgres 操作：meta_data / financial_data / public。"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from supabase import ClientOptions, create_client

_url = os.environ["SUPABASE_URL"]
_key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
_meta_client = create_client(_url, _key, ClientOptions(schema="meta_data"))
_fd_client = create_client(_url, _key, ClientOptions(schema="financial_data"))
_pub_client = create_client(_url, _key)

STOCKS_TABLE = "sehk_active_stocks"
US_STOCKS_TABLE = "us_active_stocks"


def _table(name: str):
    return _meta_client.table(name)


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


# ── financial_data 操作 ──


def insert_financial_items(rows: list[dict[str, Any]]) -> int:
    """批量 upsert us_fs_items（ON CONFLICT 跳过重复）。"""
    if not rows:
        return 0
    inserted = 0
    batch_size = 200
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            resp = (
                _fd_client.table("us_fs_items")
                .upsert(
                    batch,
                    on_conflict="ticker,fiscal_year,fiscal_period,statement,field_id",
                )
                .execute()
            )
            inserted += len(resp.data or [])
        except Exception:
            for row in batch:
                try:
                    _fd_client.table("us_fs_items").upsert(
                        row,
                        on_conflict="ticker,fiscal_year,fiscal_period,statement,field_id",
                    ).execute()
                    inserted += 1
                except Exception as inner_e:
                    print(f"  [WARN] insert_financial_items 单行失败: {inner_e}")
    return inserted


def upsert_field_defs_batch(
    defs: dict[tuple[int, str], dict[str, Any]],
) -> dict[str, int]:
    """批量写入 us_field_definitions。ON CONFLICT 跳过已有。

    返回 {'inserted': N, 'skipped': N, 'conflict': N, 'error': N}
    """
    stats: dict[str, int] = {"inserted": 0, "skipped": 0, "conflict": 0, "error": 0}
    if not defs:
        return stats

    rows = [
        {"field_id": k[0], "statement": k[1], "display_name": v}
        for k, v in defs.items()
    ]

    # 先查询已存在的 key 集合
    existing_keys: set[tuple[int, str]] = set()
    for r in rows:
        try:
            resp = (
                _fd_client.table("us_field_definitions")
                .select("field_id,statement")
                .eq("field_id", r["field_id"])
                .eq("statement", r["statement"])
                .limit(1)
                .execute()
            )
            if resp.data:
                existing_keys.add((r["field_id"], r["statement"]))
        except Exception:
            pass

    batch_size = 100
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            _fd_client.table("us_field_definitions").upsert(
                batch,
                on_conflict="field_id,statement",
            ).execute()
        except Exception:
            for r in batch:
                try:
                    _fd_client.table("us_field_definitions").upsert(
                        r,
                        on_conflict="field_id,statement",
                    ).execute()
                except Exception as inner_e:
                    print(f"  [WARN] upsert_field_defs_batch 单行失败: {inner_e}")
                    stats["error"] += 1

    for r in rows:
        key = (r["field_id"], r["statement"])
        if key in existing_keys:
            stats["skipped"] += 1
        else:
            stats["inserted"] += 1

    return stats


def check_field_def_conflicts(defs: dict[tuple[int, str], dict[str, Any]]) -> None:
    """检查 us_field_definitions 冲突——仅对已有条目做 SELECT 比对，最多查 50 条。"""
    conflicts: list[str] = []
    checked = 0
    for (fid, st), new_dn in defs.items():
        if checked > 50:
            break
        try:
            resp = (
                _fd_client.table("us_field_definitions")
                .select("display_name")
                .eq("field_id", fid)
                .eq("statement", st)
                .limit(1)
                .execute()
            )
            if resp.data:
                old_dn = resp.data[0].get("display_name", {})
                if old_dn.get("en") != new_dn.get("en"):
                    conflicts.append(
                        f"  field_id={fid:<5d} statement={st:<13s} "
                        f"旧={old_dn.get('en', '?')[:40]:<40s} 新={new_dn.get('en', '')}"
                    )
        except Exception as e:
            print(f"  [WARN] check_field_def_conflicts 查询失败: {e}")
        checked += 1
    if conflicts:
        print(f"\n  field_definitions 冲突 ({len(conflicts)} 条, 已保留库中旧值):")
        for c in conflicts:
            print(c)


def upsert_us_fs_metadata(
    ticker: str,
    currency: str,
    min_fy: int,
    max_fy: int,
    max_fp: str,
) -> str:
    """写入/更新 us_fs_metadata。返回 'inserted' | 'updated' | 'error'。"""
    try:
        resp = (
            _fd_client.table("us_fs_metadata")
            .select("min_fy,max_fy,max_fp")
            .eq("ticker", ticker)
            .limit(1)
            .execute()
        )
        if resp.data:
            old = resp.data[0]
            new_min = min(old.get("min_fy") or min_fy, min_fy)
            new_max = max(old.get("max_fy") or max_fy, max_fy)
            _fd_client.table("us_fs_metadata").update(
                {
                    "min_fy": new_min,
                    "max_fy": new_max,
                    "max_fp": max_fp,
                    "currency": currency,
                    "updated_at": datetime.now().isoformat(),
                }
            ).eq("ticker", ticker).execute()
            return "updated"
        else:
            _fd_client.table("us_fs_metadata").insert(
                {
                    "ticker": ticker,
                    "currency": currency,
                    "min_fy": min_fy,
                    "max_fy": max_fy,
                    "max_fp": max_fp,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                }
            ).execute()
            return "inserted"
    except Exception as e:
        print(f"  [WARN] upsert_us_fs_metadata 失败: {e}")
        return "error"


def get_fs_items(
    ticker: str,
    fiscal_years: list[int],
    fiscal_period: str,
    statement: str | None = None,
) -> list[dict[str, Any]]:
    """查询 us_fs_items + us_field_definitions，返回带 display_name 的行。"""
    # 查财报数据
    q = (
        _fd_client.table("us_fs_items")
        .select("fiscal_year,fiscal_period,statement,field_id,value")
        .eq("ticker", ticker)
        .eq("fiscal_period", fiscal_period)
        .in_("fiscal_year", fiscal_years)
    )
    if statement:
        q = q.eq("statement", statement)
    resp = q.execute()
    items = resp.data or []
    if not items:
        return []

    # 查字段定义
    unique_keys = {(r["field_id"], r["statement"]) for r in items}
    field_defs: dict[tuple[int, str], dict[str, Any]] = {}
    for fid, stmt in unique_keys:
        try:
            dresp = (
                _fd_client.table("us_field_definitions")
                .select("field_id,statement,display_name")
                .eq("field_id", fid)
                .eq("statement", stmt)
                .limit(1)
                .execute()
            )
            if dresp.data:
                row = dresp.data[0]
                field_defs[(fid, stmt)] = row.get("display_name", {})
        except Exception:
            pass

    # 合并 display_name
    for r in items:
        r["display_name"] = field_defs.get((r["field_id"], r["statement"]), {})

    return items


def get_pending_stocks() -> list[dict[str, Any]]:
    """返回 public.stocks 中 market=US 的全部记录。"""
    return _fetch_all_pub_stocks()


def _fetch_all_pub_stocks() -> list[dict[str, Any]]:
    """分页查询 public.stocks 中 market=US 的全部记录。"""
    stocks: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _meta_client.table("us_active_stocks")
            .select("id,ticker,company_name")
            .order("ticker")
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


def get_stock_by_ticker(ticker: str) -> dict[str, Any] | None:
    """查询单只美股（meta_data.us_active_stocks）。"""
    resp = (
        _meta_client.table("us_active_stocks")
        .select("id,ticker,company_name")
        .eq("ticker", ticker)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_stocks_by_tickers(tickers: list[str]) -> list[dict[str, Any]]:
    """批量查询美股（meta_data.us_active_stocks）。"""
    result: list[dict[str, Any]] = []
    batch_size = 500
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        resp = (
            _meta_client.table("us_active_stocks")
            .select("id,ticker,company_name")
            .in_("ticker", batch)
            .execute()
        )
        result.extend(resp.data or [])
    return result
