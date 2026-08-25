"""港交所回购公告实时处理 CLI。

子命令:
  scrape - 爬取指定日期区间的回购公告链接并写入 Supabase
  parse  - 解析未处理的回购公告 PDF（下载 → LLM 提取 → 写入 Supabase）
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

import typer

app = typer.Typer(help="港交所回购公告实时处理")


@app.command()
def scrape(
    start: Annotated[datetime, typer.Option(help="起始日期（默认今天）")] = None,
    end: Annotated[datetime, typer.Option(help="结束日期（默认同 start）")] = None,
):
    """爬取回购公告链接并写入 Supabase"""
    from rich.console import Console

    from modules.srrpt_realtime.scrape import scrape_and_save

    start_date = (start or datetime.now()).date()
    end_date = (end or datetime.combine(start_date, datetime.min.time())).date()

    results = scrape_and_save(start_date, end_date, Console())
    if any(not r.success for r in results):
        raise typer.Exit(code=1)


@app.command()
def parse(
    workers: Annotated[int, typer.Option(help="并发线程数")] = 50,
    push: Annotated[bool, typer.Option(help="推送解析结果到 hkex_repurchase_realtime_reports")] = False,
):
    """解析未处理的回购公告 PDF"""
    from rich.console import Console

    from modules.srrpt_realtime.parse import parse_all

    results = parse_all(Console(), workers=workers, push=push)
    if any(not r.success for r in results):
        raise typer.Exit(code=1)
