"""股价处理器 CLI 入口。

子命令:
  download  - 从 Tiger API 下载日K线数据到本地 JSON
  upload    - 将本地 JSON 上传到 Supabase

不指定子命令时，依次执行 download + upload。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from rich.console import Console
from tigeropen.common.consts import QuoteRight


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _build_common_parser() -> argparse.ArgumentParser:
    """构建公共参数 parser，供子命令继承。"""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--tickers", type=str, default="", help="股票代码，逗号分隔（默认全部活跃港股）")
    common.add_argument("--start-date", type=_parse_date, default=date(2015, 1, 1), help="起始日期（默认 2015-01-01）")
    common.add_argument("--end-date", type=_parse_date, default=date.today(), help="结束日期（默认今天）")
    common.add_argument("--right", choices=["NR", "BR", "both"], default="both", help="复权方式（默认 both）")
    return common


def parse_args() -> argparse.Namespace:
    common = _build_common_parser()

    p = argparse.ArgumentParser(description="港股日K线数据处理器（Tiger API）", parents=[common])
    sub = p.add_subparsers(dest="command")
    sub.add_parser("download", parents=[common], help="下载日K线数据")
    upload_p = sub.add_parser("upload", parents=[common], help="上传日K线数据到 Supabase")
    upload_p.add_argument("--input-dir", type=str, default=None, help="JSON 文件目录")
    upload_p.add_argument("--dry-run", action="store_true", help="仅打印，不实际上传")

    return p.parse_args()


def _resolve_rights(right_arg: str) -> list[QuoteRight]:
    """将 --right 参数转为 QuoteRight 列表。"""
    if right_arg == "NR":
        return [QuoteRight.NR]
    if right_arg == "BR":
        return [QuoteRight.BR]
    return [QuoteRight.NR, QuoteRight.BR]


def _parse_tickers(raw: str) -> list[str]:
    """解析逗号分隔的股票代码。"""
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _run_download(args: argparse.Namespace, console: Console) -> None:
    from app.stock_price_handler.downloader import StockPriceDownloader
    from modules.stock_price.tiger_kline import TigerKlineFetcher

    tickers = _parse_tickers(args.tickers)
    rights = _resolve_rights(args.right)

    fetcher = TigerKlineFetcher()
    dl = StockPriceDownloader(fetcher=fetcher, console=console)
    results = dl.download(tickers, args.start_date, args.end_date, rights)

    failed = [r for r in results if not r.success]
    if failed:
        console.print(f"\n[red]{len(failed)} 个任务下载失败:[/red]")
        for r in failed[:10]:
            console.print(f"  {r.stock_code} ({r.right}): {r.error}")
        if len(failed) > 10:
            console.print(f"  ... 共 {len(failed)} 个失败")


def _run_upload(args: argparse.Namespace, console: Console) -> None:
    from pathlib import Path

    from app.stock_price_handler.uploader import DEFAULT_INPUT_DIR, StockPriceUploader

    input_dir = Path(args.input_dir) if getattr(args, "input_dir", None) else DEFAULT_INPUT_DIR
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


def main() -> None:
    args = parse_args()
    console = Console()

    if args.command == "download":
        _run_download(args, console)
    elif args.command == "upload":
        _run_upload(args, console)
    elif args.command is None:
        # 默认：先下载再上传
        _run_download(args, console)
        console.print()
        _run_upload(args, console)
    else:
        console.print(f"[red]未知子命令: {args.command}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
