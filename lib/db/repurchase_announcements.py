"""回购公告链接操作（market_data.hkex_repurchase_announcements）。"""

from __future__ import annotations

from typing import Any

from lib.db.client import _md_client


def upsert_repurchase_announcements(records: list[dict[str, Any]]) -> int:
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
    urls: set[str] = set()
    page_size = 1000
    offset = 0
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
    (
        _md_client.table("hkex_repurchase_announcements")
        .update({"parsed": True})
        .eq("stock_code", stock_code)
        .eq("release_time", release_time)
        .eq("document_url", document_url)
        .execute()
    )
