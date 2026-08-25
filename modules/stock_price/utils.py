"""stock_price 模块公共工具函数。"""

from __future__ import annotations

import argparse
from datetime import date


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


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


def build_download_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tickers", type=str, default="", help="股票代码，逗号分隔")
    parser.add_argument(
        "--start-date", type=parse_date, default=date(2015, 1, 1), help="起始日期"
    )
    parser.add_argument(
        "--end-date", type=parse_date, default=date.today(), help="结束日期"
    )
    parser.add_argument(
        "--right", choices=["NR", "BR", "both"], default="both", help="复权方式"
    )
    parser.add_argument(
        "--fetcher",
        choices=["tiger", "akshare", "sina"],
        default="akshare",
        help="数据源 (默认: akshare)",
    )
