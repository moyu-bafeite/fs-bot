"""爬取 HKEX 年报/中报元数据，写入 Supabase DB。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from lib.db import (
    get_excluded_keywords,
    get_latest_filing_date,
    log_error,
    upsert_filings,
)
from lib.hkex import fetch_filings
from lib.parser import (
    build_exclude_pattern,
    filter_annual_and_interim,
    normalize_ticker,
)

START_YEAR = 2010


def scrape(
    tickers: list[str],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    full: bool = False,
) -> int:
    """爬取元数据并写入 DB，返回写入记录数。"""
    now = datetime.now()
    user_specified_from = date_from is not None
    if date_to is None:
        date_to = now

    exclude_keywords = get_excluded_keywords()
    exclude_pattern = build_exclude_pattern(exclude_keywords)
    if exclude_keywords:
        print(f"已加载 {len(exclude_keywords)} 个排除关键词")

    total = 0
    for ticker in tickers:
        code = normalize_ticker(ticker)

        # 确定查询起始日期
        if full:
            effective_from = datetime(START_YEAR, 1, 1)
        elif user_specified_from:
            effective_from = date_from
        else:
            latest = get_latest_filing_date(code)
            if latest:
                # 从最新记录的当月 1 日开始
                ld = datetime.strptime(latest, "%Y-%m-%d")
                effective_from = datetime(ld.year, ld.month, 1)
                print(
                    f"[{code}] 增量模式：从 {effective_from.strftime('%Y-%m-%d')} 开始"
                )
            else:
                effective_from = datetime(START_YEAR, 1, 1)
                print(f"[{code}] 全量模式：无历史记录")

        try:
            raw = fetch_filings(code, effective_from, date_to)
            filings = filter_annual_and_interim(raw, exclude_pattern)
            if filings:
                upsert_filings(filings)
                total += len(filings)
            print(f"[{code}] 获取 {len(raw)} 条，筛选 {len(filings)} 条年报/中报")
        except Exception as e:
            log_error(
                "scrape",
                str(e),
                stock_code=code,
                details={
                    "ticker": ticker,
                    "date_from": effective_from.isoformat(),
                    "date_to": date_to.isoformat(),
                },
            )
            print(f"[{code}] 错误: {e}", file=sys.stderr)

    return total


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="爬取 HKEX 年报/中报元数据")
    parser.add_argument("--tickers", nargs="+", required=True, help="股票代码列表")
    parser.add_argument("--from", dest="date_from", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--full", action="store_true", help="全量爬取（从 2005 年起）")
    return parser
