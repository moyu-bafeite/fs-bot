"""港股日K线数据 ETL CLI。

子命令:
  download - 从 Tiger API 下载日K线数据
  upload   - 上传日K线数据到 Supabase

不指定子命令时，依次执行 download + upload。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _build_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tickers", type=str, default="", help="股票代码，逗号分隔")
    parser.add_argument(
        "--start-date", type=_parse_date, default=date(2015, 1, 1), help="起始日期"
    )
    parser.add_argument(
        "--end-date", type=_parse_date, default=date.today(), help="结束日期"
    )
    parser.add_argument(
        "--right", choices=["NR", "BR", "both"], default="both", help="复权方式"
    )


def register(subparsers) -> None:
    p = subparsers.add_parser("stock-price", help="港股日K线数据 ETL")
    _build_common_args(p)

    sub = p.add_subparsers(dest="stock_price_command")

    dl = sub.add_parser("download", help="下载日K线数据")
    _build_common_args(dl)

    up = sub.add_parser("upload", help="上传日K线数据到 Supabase")
    _build_common_args(up)
    up.add_argument("--input-dir", type=str, default=None, help="JSON 文件目录")
    up.add_argument("--dry-run", action="store_true", help="仅打印，不实际上传")

    p.set_defaults(func=run)


def _resolve_rights(right_arg: str):
    from tigeropen.common.consts import QuoteRight

    if right_arg == "NR":
        return [QuoteRight.NR]
    if right_arg == "BR":
        return [QuoteRight.BR]
    return [QuoteRight.NR, QuoteRight.BR]


def _parse_tickers(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def run(args: argparse.Namespace) -> None:
    from rich.console import Console

    console = Console()
    command = getattr(args, "stock_price_command", None)

    if command == "download":
        _run_download(args, console)
    elif command == "upload":
        _run_upload(args, console)
    elif command is None:
        _run_download(args, console)
        console.print()
        _run_upload(args, console)
    else:
        console.print(f"[red]未知子命令: {command}[/red]")
        sys.exit(1)


def _run_download(args, console) -> None:
    from modules.stock_price.cli_helpers import StockPriceDownloader
    from modules.stock_price.tiger_kline import TigerKlineFetcher

    tickers = _parse_tickers(args.tickers)
    rights = _resolve_rights(args.right)

    fetcher = TigerKlineFetcher()
    dl = StockPriceDownloader(fetcher=fetcher, console=console)
    dl.download(tickers, args.start_date, args.end_date, rights)


def _run_upload(args, console) -> None:
    from pathlib import Path

    from modules.stock_price.upload import DEFAULT_INPUT_DIR, StockPriceUploader

    input_dir = (
        Path(args.input_dir) if getattr(args, "input_dir", None) else DEFAULT_INPUT_DIR
    )
    files = sorted(f for f in input_dir.glob("*.json") if not f.name.startswith("_"))

    if not files:
        console.print(f"[yellow]未找到 JSON 文件: {input_dir}[/yellow]")
        return

    uploader = StockPriceUploader(console=console)
    results = uploader.upload(files, dry_run=getattr(args, "dry_run", False))

    failed = [r for r in results if not r.success]
    if failed:
        console.print(f"\n[red]{len(failed)} 个文件上传失败:[/red]")
        for r in failed:
            console.print(f"  {r.file.name}: {r.error}")
