"""港股日K线数据 ETL CLI。

子命令:
  download - 下载日K线数据（支持 --fetcher 选择数据源: tiger / akshare）
  upload   - 上传日K线数据到 Supabase
  check    - 检查数据质量（NR/BR 一致性等）
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from modules.stock_price.utils import (
    build_download_args,
    parse_date,
    parse_tickers,
    resolve_rights,
)


def register(subparsers) -> None:
    p = subparsers.add_parser("stock-price", help="港股日K线数据 ETL")
    sub = p.add_subparsers(dest="stock_price_command")

    dl = sub.add_parser("download", help="下载日K线数据")
    build_download_args(dl)

    up = sub.add_parser("upload", help="上传日K线数据到 Supabase")
    up.add_argument("--tickers", type=str, default="", help="股票代码，逗号分隔（为空则上传全部）")
    up.add_argument("--start-date", type=parse_date, default=date.today(), help="只上传该日期之后的数据（默认今天）")
    up.add_argument("--end-date", type=parse_date, default=date.today(), help="只上传该日期之前的数据（默认今天）")
    up.add_argument("--dry-run", action="store_true", help="仅打印，不实际上传")

    ck = sub.add_parser("check", help="检查数据质量")
    ck.add_argument("--file", type=str, default=None, help="指定文件名（如 00837_NR.json），为空则检查全部")

    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    from rich.console import Console

    console = Console()
    command = getattr(args, "stock_price_command", None)

    if command == "download":
        _run_download(args, console)
    elif command == "upload":
        _run_upload(args, console)
    elif command == "check":
        _run_check(args, console)
    else:
        console.print("[red]请指定子命令: download / upload / check[/red]")
        sys.exit(1)


def _run_download(args, console) -> None:
    from modules.stock_price.download import StockPriceDownloader, create_fetcher

    tickers = parse_tickers(args.tickers)
    rights = resolve_rights(args.right)
    fetcher_name = getattr(args, "fetcher", "akshare")

    fetcher = create_fetcher(fetcher_name)
    console.print(f"数据源: {fetcher_name}")
    dl = StockPriceDownloader(fetcher=fetcher, console=console)
    dl.download(tickers, args.start_date, args.end_date, rights)


def _run_upload(args, console) -> None:
    from modules.stock_price.upload import StockPriceUploader

    tickers = parse_tickers(args.tickers)

    uploader = StockPriceUploader(console=console)
    results = uploader.upload(
        tickers=tickers,
        start_date=getattr(args, "start_date", None),
        end_date=getattr(args, "end_date", None),
        dry_run=getattr(args, "dry_run", False),
    )

    failed = [r for r in results if not r.success]
    if failed:
        console.print(f"\n[red]{len(failed)} 组上传失败:[/red]")
        for r in failed:
            console.print(f"  {r.right}: {r.error}")


def _run_check(args, console) -> None:
    from modules.stock_price.check import run_checks

    file_arg = getattr(args, "file", None)
    report = run_checks(file_arg=file_arg, console=console)
    if not report.ok:
        sys.exit(1)
