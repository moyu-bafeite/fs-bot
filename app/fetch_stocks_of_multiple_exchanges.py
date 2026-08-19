"""查询每个 end_date 记录不止一条的 stock_code。"""

from __future__ import annotations

import argparse
from collections import Counter

from rich.console import Console
from rich.table import Table

from lib.db import _md_client, get_stock_names

console = Console()


def fetch_all_stock_end_dates() -> list[tuple[str, str]]:
    """分页获取所有 (stock_code, end_date) 对。"""
    records: list[tuple[str, str]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _md_client.table("hk_repurchase_actions")
            .select("stock_code,end_date")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            break
        for row in rows:
            stock_code = row["stock_code"]
            end_date = row["end_date"]
            if stock_code and end_date:
                records.append((stock_code, end_date))
        if len(rows) < page_size:
            break
        offset += page_size
    return records


def find_stock_codes_with_duplicate_end_dates(
    records: list[tuple[str, str]],
) -> list[str]:
    """找出有重复 end_date 记录的 stock_code 列表（去重，已排序）。"""
    counter = Counter(records)
    stock_codes: set[str] = set()
    for (stock_code, _end_date), count in counter.items():
        if count > 1:
            stock_codes.add(stock_code)
    return sorted(stock_codes)


def print_results(stock_codes: list[str]) -> None:
    """使用 rich 打印结果表格，无外边框。"""
    if not stock_codes:
        console.print("  [green]没有发现重复记录。[/green]")
        return

    stock_names = get_stock_names(stock_codes)

    table = Table(
        title="每个 end_date 记录不止一条的 stock_code",
        show_header=True,
        header_style="bold",
        box=None,
    )
    table.add_column("Stock Code", style="bold", width=12)
    table.add_column("Stock Name", width=20)

    for code in stock_codes:
        name = stock_names.get(code, {})
        table.add_row(code, name.get("zh-CN", ""))

    console.print()
    console.print(table)
    console.print()
    console.print(f"  共 {len(stock_codes)} 只股票有重复记录。")


def run(args: argparse.Namespace) -> None:
    console.print("  正在查询 hk_repurchase_actions 表...")
    records = fetch_all_stock_end_dates()
    console.print(f"  共获取 {len(records):,} 条记录。")

    stock_codes = find_stock_codes_with_duplicate_end_dates(records)
    print_results(stock_codes)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="查询每个 end_date 记录不止一条的 stock_code")
    return p.parse_args()


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    run(args)
