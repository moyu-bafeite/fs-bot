"""港交所回购公告实时处理 CLI。

子命令:
  scrape - 爬取指定日期区间的回购公告链接并写入 Supabase
  parse  - 解析未处理的回购公告 PDF（下载 → LLM 提取 → 写入 Supabase）
"""

from __future__ import annotations

import argparse
from datetime import date


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def register(subparsers) -> None:
    p = subparsers.add_parser("srrpt-realtime", help="港交所回购公告链接爬虫")
    sub = p.add_subparsers(dest="srrpt_realtime_command")

    sc = sub.add_parser("scrape", help="爬取回购公告链接")
    sc.add_argument("--start", required=True, type=_parse_date, help="起始日期")
    sc.add_argument("--end", required=True, type=_parse_date, help="结束日期")

    ps = sub.add_parser("parse", help="解析未处理的回购公告 PDF")
    ps.add_argument("--workers", type=int, default=2000, help="并发线程数")

    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    cmd = getattr(args, "srrpt_realtime_command", None)
    if cmd == "scrape":
        _run_scrape(args)
    elif cmd == "parse":
        _run_parse(args)
    else:
        from rich.console import Console

        Console().print("[yellow]请指定子命令: scrape 或 parse[/yellow]")


def _run_scrape(args: argparse.Namespace) -> None:
    from rich.console import Console
    from modules.srrpt_realtime.scrape import scrape_and_save

    scrape_and_save(args.start, args.end, Console())


def _run_parse(args: argparse.Namespace) -> None:
    from rich.console import Console
    from modules.srrpt_realtime.parse import parse_all

    parse_all(Console(), workers=args.workers)
