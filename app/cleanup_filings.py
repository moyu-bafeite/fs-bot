"""清理 filings 表中匹配排除关键词的噪声记录。"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from lib.db import (
    delete_filings_by_ids,
    get_excluded_keywords,
    get_filings_by_keywords,
    log_error,
)

console = Console()


def cleanup(stock_code: str | None = None) -> int:
    """清理噪声记录，返回删除数量。"""
    keywords = get_excluded_keywords()
    if not keywords:
        console.print("[yellow]排除关键词表为空，请先添加关键词[/yellow]")
        return 0

    console.print(f"已加载 [cyan]{len(keywords)}[/cyan] 个排除关键词")

    records = get_filings_by_keywords(keywords)
    if not records:
        console.print("[green]没有匹配的噪声记录[/green]")
        return 0

    if stock_code:
        records = [r for r in records if r["stock_code"] == stock_code]
        if not records:
            console.print(f"[green]股票 {stock_code} 没有匹配的噪声记录[/green]")
            return 0

    _display_records(records, keywords)

    if not Confirm.ask(f"\n确认删除以上 [red]{len(records)}[/red] 条记录？"):
        console.print("[yellow]已取消[/yellow]")
        return 0

    ids = [r["id"] for r in records]
    deleted = delete_filings_by_ids(ids)
    console.print(f"[green]已删除 {deleted} 条记录[/green]")

    log_error(
        "cleanup",
        f"批量删除 {deleted} 条噪声记录",
        details={
            "deleted_ids": ids[:100],
            "keywords": keywords,
            "stock_code": stock_code,
        },
    )

    return deleted


def _display_records(records: list[dict], keywords: list[str]) -> None:
    """用 rich 表格展示待删除记录。"""
    table = Table(title=f"待删除的噪声记录（共 {len(records)} 条）")
    table.add_column("#", justify="right", style="dim", width=5)
    table.add_column("股票", style="cyan", width=8)
    table.add_column("类型", width=8)
    table.add_column("年份", justify="right", width=6)
    table.add_column("命中关键词", style="yellow", width=20)
    table.add_column("标题", max_width=60)
    table.add_column("链接", style="blue", max_width=70)

    for i, rec in enumerate(records, 1):
        matched = _find_matched_keyword(rec["title"], keywords)
        table.add_row(
            str(i),
            rec["stock_code"],
            rec.get("filing_type", ""),
            str(rec.get("report_year", "")),
            matched,
            rec["title"],
            rec.get("file_url", ""),
        )

    console.print(table)


def _find_matched_keyword(title: str, keywords: list[str]) -> str:
    """找到标题中命中的第一个关键词。"""
    title_lower = title.lower()
    for kw in keywords:
        if kw.lower() in title_lower:
            return kw
    return ""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="清理 filings 表中的噪声记录")
    parser.add_argument(
        "--stock-code", dest="stock_code", help="限定股票代码（如 00005）"
    )
    return parser
