"""下载 HKEX 活跃股票列表，只保留主板正股，写入 sehk_active_stocks 表。"""

from __future__ import annotations

import re

import httpx
from opencc import OpenCC

from lib.db import upsert_stocks

HKEX_EN_URL = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json"
HKEX_ZH_URL = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_c.json"

_EXCLUDE_KEYWORDS = re.compile(
    r"ETF|REIT|FUND|TRUST|BOND|NOTE|TBILL|GILT", re.IGNORECASE
)

_DERIVATIVE_PATTERN = re.compile(
    r"PRC B\d|W\d{2,4}$|\sN\d{3,4}|\sB\d{3,4}|HSDIV", re.IGNORECASE
)

_LEVERAGED_INVERSE = re.compile(r"^(FL|XL|FI|XI)\d?", re.IGNORECASE)

_ETF_PATTERN = re.compile(
    r"^(CSOP|ISHARES|GX |A GX|A CSOP|AMUNDI|PREMIA|INVESCO|HGI |BOCGBA|"
    r"HSCMS|PKSA|TRMSCI|A CICC|A BOS|A HS|A TK|A VP|A DOO|A PANDO|"
    r"FA |FB |MBC|PING AN HK|WISE NEWECON|X TR[A-Z]|"
    r"PP [A-Z]|BOS HSK|CAM [A-Z]|FG HS|HS [A-Z]|ICBCU|"
    r"EFUND|X TRMSCI|SAMSUNG REITS|VALUEGOLD|"
    r"F SSIF|F GX|A SS |A HSJP|A GXS|SAMSUNG |ICBCCSOP|F SAMSUNG|"
    r"PANDO |PA [A-Z]|VP |BOS \d|TR MSCI|X CSOP|XA |PPKSA|CMS |"
    r"A MBC|A CAM)",
    re.IGNORECASE,
)

_t2s = OpenCC("t2s")


def _is_main_board_equity(code: str, name: str) -> bool:
    """判断是否为主板正股：5位代码以0开头，排除债券/结构化产品/ETF等。"""
    if len(code) != 5 or not code.startswith("0"):
        return False
    if code[:2] in ("04", "05"):
        return False
    if "02801" <= code <= "02848":
        return False
    if _EXCLUDE_KEYWORDS.search(name) or _DERIVATIVE_PATTERN.search(name):
        return False
    if _LEVERAGED_INVERSE.search(name) or _ETF_PATTERN.search(name):
        return False
    if name.endswith("-U"):
        return False
    return True


def sync() -> int:
    """下载并写入，返回写入记录数。"""
    en_data = httpx.get(HKEX_EN_URL, timeout=30).json()
    zh_data = httpx.get(HKEX_ZH_URL, timeout=30).json()

    zh_map: dict[str, str] = {item["c"]: item["n"] for item in zh_data}

    records = []
    for item in en_data:
        code, en_name = item["c"], item["n"]
        if not _is_main_board_equity(code, en_name):
            continue
        zh_hk = zh_map.get(code, "")
        zh_cn = _t2s.convert(zh_hk) if zh_hk else ""
        records.append(
            {
                "stock_code": code,
                "stock_name": {"en": en_name, "zh-CN": zh_cn, "zh-HK": zh_hk},
                "hkex_id": item["i"],
            }
        )

    upsert_stocks(records)
    return len(records)
