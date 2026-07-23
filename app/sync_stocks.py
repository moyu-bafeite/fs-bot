"""下载 HKEX 活跃股票列表，只保留主板正股，写入 sehk_active_stocks 表。"""

from __future__ import annotations

import re

import httpx

from lib.db import upsert_stocks
from lib.hkex import HKEX_STOCK_LIST_URL

_EXCLUDE_KEYWORDS = re.compile(
    r"ETF|REIT|FUND|TRUST|BOND|NOTE|TBILL|GILT", re.IGNORECASE
)


def _is_main_board_equity(code: str, name: str) -> bool:
    """判断是否为主板正股：5位代码以0开头，排除债券/结构化产品/ETF等。"""
    if len(code) != 5 or not code.startswith("0"):
        return False
    if code[:2] in ("04", "05", "07"):
        return False
    if _EXCLUDE_KEYWORDS.search(name):
        return False
    return True


def sync() -> int:
    """下载并写入，返回写入记录数。"""
    resp = httpx.get(HKEX_STOCK_LIST_URL, timeout=30)
    resp.raise_for_status()
    stocks = resp.json()

    records = []
    for item in stocks:
        code, name = item["c"], item["n"]
        if not _is_main_board_equity(code, name):
            continue
        records.append(
            {
                "stock_code": code,
                "stock_name": name,
                "hkex_id": item["i"],
            }
        )

    upsert_stocks(records)
    return len(records)
