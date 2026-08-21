"""港交所股份回购报告（SRRPT）批量下载器 CLI 入口。"""

from __future__ import annotations

import argparse
from datetime import date

from rich.console import Console

from modules.hkex_srrpt.download_hkex_srrpt import HKEXSrrptDownloader


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="批量下载港交所股份回购报告（SRRPT）")
    p.add_argument(
        "--start", required=True, type=_parse_date, help="起始日期（YYYY-MM-DD）"
    )
    p.add_argument(
        "--end", required=True, type=_parse_date, help="结束日期（YYYY-MM-DD）"
    )
    p.add_argument(
        "--output-dir", default=None, help="输出目录（默认 downloads/srrpt）"
    )
    p.add_argument("--workers", type=int, default=5, help="并发线程数（默认 5）")
    p.add_argument("--no-skip", action="store_true", help="不跳过已存在的文件")
    return p.parse_args()


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()

    console = Console()
    kwargs: dict = {
        "console": console,
        "workers": args.workers,
        "skip_existing": not args.no_skip,
    }
    if args.output_dir is not None:
        kwargs["output_dir"] = args.output_dir

    dl = HKEXSrrptDownloader(**kwargs)
    results = dl.download_range(args.start, args.end)

    failed = [r for r in results if not r.success]
    if failed:
        console.print(f"\n[red]{len(failed)} 个文件下载失败:[/red]")
        for r in failed:
            console.print(f"  {r.target_date}: {r.error}")
