"""stock_price 模块公共工具函数。"""

from __future__ import annotations


def parse_tickers(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def resolve_rights(right_arg: str):
    from tigeropen.common.consts import QuoteRight

    if right_arg == "NR":
        return [QuoteRight.NR]
    if right_arg == "BR":
        return [QuoteRight.BR]
    return [QuoteRight.NR, QuoteRight.BR]
