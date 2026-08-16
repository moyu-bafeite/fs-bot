#!/usr/bin/env python3
"""从 SEC EDGAR 拉取每家公司的全量 Form 4 索引，写入 data/form4/_index/。

edgartools 内置限流（滑动窗口 9 req/s），无需外部 limiter。
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from edgar import Company, set_identity
from rich.console import Console
from rich.table import Table

from lib.db import get_all_fs_tickers

console = Console()

START_DATE = "2015-01-01"


@dataclass
class IndexResult:
    ticker: str
    ok: bool = False
    filing_count: int = 0
    error_msg: str = ""


def fetch_index_one_ticker(ticker: str, index_dir: Path) -> IndexResult:
    """拉取单只股票的 Form 4 索引，写入 _index/[ticker].json。"""
    result = IndexResult(ticker=ticker)
    try:
        bare_ticker = ticker.removeprefix("US.")
        company = Company(bare_ticker)
        filing_list = company.get_filings(form=4, date=f"{START_DATE}:")

        filings: list[dict] = []
        for f in filing_list:
            filings.append(
                {
                    "accession_no": f.accession_no,
                    "filing_date": str(f.filing_date) if f.filing_date else None,
                    "form": f.form or "4",
                    "cik": str(f.cik),
                    "company_name": str(f.company),
                }
            )

        out_path = index_dir / f"{ticker}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "ticker": ticker,
                    "fetched_at": datetime.now().isoformat(),
                    "filings": filings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        result.filing_count = len(filings)
        result.ok = True
    except Exception as e:
        result.error_msg = str(e)
    return result


def run(args: argparse.Namespace) -> None:
    set_identity("Finsco support@finsco.io")

    data_dir = Path(args.data_dir)
    index_dir = data_dir / "_index"

    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = get_all_fs_tickers()

    if args.max_stocks and args.max_stocks > 0:
        tickers = tickers[: args.max_stocks]

    total = len(tickers)
    if total == 0:
        console.print("  无待处理股票")
        return

    console.print(f"  待处理: {total} 只  并发: {args.workers}")

    run_start = datetime.now()
    start_time = time.time()

    success_results: list[IndexResult] = []
    fail_results: list[IndexResult] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_index_one_ticker, ticker, index_dir): ticker
            for ticker in tickers
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result = future.result()
            except Exception as e:
                result = IndexResult(ticker=ticker, error_msg=str(e))

            if result.ok:
                success_results.append(result)
            else:
                fail_results.append(result)

            done = len(success_results) + len(fail_results)
            status = "[green]OK[/green]" if result.ok else "[red]FAIL[/red]"
            detail = f"f={result.filing_count}" if result.ok else result.error_msg[:60]
            console.print(f"  [{done:>4d}/{total}] {ticker:<12} {detail} {status}")

    elapsed = time.time() - start_time

    summary = Table(
        title="索引拉取完成", show_header=True, header_style="bold", box=None
    )
    summary.add_column("项目", style="bold")
    summary.add_column("值")
    summary.add_row("成功", f"{len(success_results):,}")
    summary.add_row("失败", f"{len(fail_results):,}")
    summary.add_row("总 filings", f"{sum(r.filing_count for r in success_results):,}")
    summary.add_row("耗时", f"{elapsed / 60:.1f} 分钟")
    console.print()
    console.print(summary)

    if fail_results:
        fail_table = Table(
            title="失败列表", show_header=True, header_style="bold red", box=None
        )
        fail_table.add_column("Ticker", width=12)
        fail_table.add_column("Error")
        for r in sorted(fail_results, key=lambda r: r.ticker):
            fail_table.add_row(r.ticker, r.error_msg[:80])
        console.print()
        console.print(fail_table)

    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = run_start.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"fetch_us_form4_index_{ts}.json"
    log_path.write_text(
        json.dumps(
            {
                "run_at": run_start.isoformat(),
                "elapsed_seconds": round(elapsed, 1),
                "summary": {
                    "total": total,
                    "success": len(success_results),
                    "fail": len(fail_results),
                    "filings": sum(r.filing_count for r in success_results),
                },
                "fail_list": [
                    {"ticker": r.ticker, "error": r.error_msg}
                    for r in sorted(fail_results, key=lambda r: r.ticker)
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    console.print(f"\n  日志已写入: {log_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="从 SEC EDGAR 拉取 Form 4 全量索引（多线程）"
    )
    p.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="逗号分隔的 ticker 列表（US.XXX 格式）",
    )
    p.add_argument("--max-stocks", type=int, default=0, help="最多处理 N 只 (0=不限)")
    p.add_argument(
        "--workers", type=int, default=8, help="并发线程数 (默认 8, 最大 20)"
    )
    p.add_argument(
        "--data-dir", type=str, default="data/form4", help="数据目录 (默认 data/form4/)"
    )
    p.add_argument("--quiet", action="store_true", help="cron 模式")
    args = p.parse_args()
    if args.workers < 1 or args.workers > 20:
        p.error("--workers 范围 1-20")
    return args


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
