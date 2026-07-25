#!/usr/bin/env python3
"""美股财报原始数据抓取脚本（行式存储 / cronjob 友好）。"""

from __future__ import annotations

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

import futu as ft
from rich.console import Console
from rich.table import Table

from lib.db import (
    check_field_def_conflicts,
    get_pending_stocks,
    get_stock_by_ticker,
    insert_financial_items,
    upsert_field_defs_batch,
    upsert_us_fs_metadata,
)

console = Console()

STATEMENT_CONFIG = [
    (1, "income", [11]),
    (2, "balance_sheet", [9]),
    (3, "cash_flow", [11]),
]

F10_TO_PERIOD = {
    1: "q1",
    2: "q2",
    3: "q3",
    4: "q4",
    5: "h1",
    6: "9m",
    7: "annual",
    8: "quarterly",
    9: "quarterly_annual",
    10: "mul_quarterly",
    11: "cumulative_quarterly",
}

PERIOD_TO_MAX_FP = {
    "q1": "Q1",
    "q2": "H1",
    "h1": "H1",
    "q3": "9M",
    "9m": "9M",
    "q4": "ANNUAL",
    "annual": "ANNUAL",
    "quarterly_annual": "ANNUAL",
}

MAX_FP_ORDER = {
    "Q1": 1,
    "H1": 2,
    "9M": 3,
    "ANNUAL": 4,
}

BS_FTYPE_TO_PERIOD = {
    1: "q1",
    2: "h1",
    3: "9m",
    4: "annual",
}


@dataclass
class StockResult:
    ticker: str
    currency: str = ""
    row_count: int = 0
    min_fy: int = 0
    max_fy: int = 0
    max_fp: str = "ANNUAL"
    fd_inserted: int = 0
    fd_skipped: int = 0
    fd_error: int = 0
    meta_result: str = "error"
    ok: bool = False
    error_msg: str = ""


def get_stock_list(args: argparse.Namespace) -> list[dict]:
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        result: list[dict] = []
        for t in tickers:
            row = get_stock_by_ticker(t)
            if row:
                result.append(row)
            else:
                console.print(f"  [yellow]ticker 不在 stocks 表中: {t}[/yellow]")
        return result
    return get_pending_stocks()


def fetch_reports(
    ctx: ft.OpenQuoteContext,
    ticker: str,
    interval: float,
) -> list[tuple[str, dict]]:
    tagged: list[tuple[str, dict]] = []

    for st_type, st_key, fin_types in STATEMENT_CONFIG:
        for fin_type in fin_types:
            next_key = None
            while True:
                ret, data = ctx.get_financials_statements(
                    ticker,
                    statement_type=st_type,
                    financial_type=fin_type,
                    num=50,
                    next_key=next_key,
                )
                if ret != ft.RET_OK:
                    break
                for report in data.get("report_list", []):
                    tagged.append((st_key, report))
                next_key = data.get("next_key")
                if not next_key or next_key == "-1":
                    break
                time.sleep(interval)
        time.sleep(interval)

    return tagged


def reports_to_rows(tagged: list[tuple[str, dict]]) -> list[dict]:
    rows: list[dict] = []
    for st_key, report in tagged:
        fy = report.get("fiscal_year")
        if not fy:
            continue
        ftype = report.get("financial_type", 10)
        if st_key == "balance_sheet":
            period = BS_FTYPE_TO_PERIOD.get(ftype, "annual")
        else:
            period = F10_TO_PERIOD.get(ftype, "annual")
        for item in report.get("item_list", []):
            fid = item.get("field_id")
            if fid is None:
                continue
            rows.append(
                {
                    "fiscal_year": fy,
                    "fiscal_period": period,
                    "statement": st_key,
                    "field_id": fid,
                    "value": float(item.get("data", 0.0)),
                }
            )
    return rows


def get_currency(tagged: list[tuple[str, dict]]) -> str:
    for _, r in tagged:
        cc = r.get("currency_code")
        if cc:
            return cc
    return "USD"


def process_one_stock(
    ctx: ft.OpenQuoteContext,
    api_lock: threading.Lock,
    lock: threading.Lock,
    idx: int,
    total: int,
    quiet: bool,
    stock: dict,
    interval: float,
    dry_run: bool,
) -> StockResult:
    """处理单只股票的完整流程（在 worker 线程中执行）。"""
    ticker = stock["ticker"]
    result = StockResult(ticker=ticker)

    if not quiet:
        with lock:
            console.print(f"  [{idx:>4d}/{total}] {ticker} - 开始抓取...")

    try:
        with api_lock:
            tagged = fetch_reports(ctx, ticker, interval)

        if not tagged:
            raise ValueError("无数据")

        if not quiet:
            with lock:
                console.print(
                    f"  [{idx:>4d}/{total}] {ticker} - API 完成, {len(tagged)} 条报告"
                )

        rows = reports_to_rows(tagged)
        currency = get_currency(tagged)
        years = [r.get("fiscal_year") for _, r in tagged if r.get("fiscal_year")]
        max_fy = max(years) if years else (datetime.now().year - 1)
        min_fy = max(2010, min(years)) if years else 2010
        latest_periods = [
            PERIOD_TO_MAX_FP.get(
                F10_TO_PERIOD.get(r.get("financial_type", 10), "annual"), "ANNUAL"
            )
            for _, r in tagged
            if r.get("fiscal_year") == max_fy
        ]
        max_fp = (
            max(latest_periods, key=lambda p: MAX_FP_ORDER.get(p, 0))
            if latest_periods
            else "ANNUAL"
        )

        for r in rows:
            r["ticker"] = ticker

        if not dry_run:
            result.row_count = insert_financial_items(rows)

            stock_fd: dict[tuple[int, str], dict] = {}
            for st_key, report in tagged:
                for item in report.get("item_list", []):
                    fid = item.get("field_id")
                    dn = item.get("display_name", "")
                    if fid and dn:
                        stock_fd.setdefault((fid, st_key), {"en": dn})

            fd_stats = upsert_field_defs_batch(stock_fd)
            result.fd_inserted = fd_stats.get("inserted", 0)
            result.fd_skipped = fd_stats.get("skipped", 0)
            result.fd_error = fd_stats.get("error", 0)

            if fd_stats.get("skipped", 0) > 0:
                check_field_def_conflicts(stock_fd)

            result.meta_result = upsert_us_fs_metadata(
                ticker, currency, min_fy, max_fy, max_fp
            )
        else:
            result.row_count = len(rows)

        result.currency = currency
        result.min_fy = min_fy
        result.max_fy = max_fy
        result.max_fp = max_fp
        result.ok = result.row_count > 0

    except Exception as e:
        result.error_msg = str(e)

    if not quiet:
        with lock:
            if result.ok:
                fy_range = f"{result.min_fy}-{result.max_fy}"
                console.print(
                    f"  [{idx:>4d}/{total}] {ticker} - "
                    f"{result.currency} {result.row_count}r {fy_range} {result.max_fp} [green]OK[/green]"
                )
            else:
                console.print(
                    f"  [{idx:>4d}/{total}] {ticker} - [red]FAIL[/red] {result.error_msg[:50]}"
                )

    return result


def run(args: argparse.Namespace) -> None:
    stocks = get_stock_list(args)
    total = len(stocks)
    if args.max_stocks and args.max_stocks > 0:
        stocks = stocks[: args.max_stocks]
        total = len(stocks)

    if total == 0:
        console.print("  无待处理股票")
        return

    console.print(f"  待处理: {total} 只  并发: {args.workers}")

    try:
        ctx = ft.OpenQuoteContext(host="127.0.0.1", port=11111)
    except Exception as e:
        console.print(f"  [red]连接 FutuOpenD 失败: {e}[/red]")
        return
    console.print("  已连接 FutuOpenD\n")

    start_time = time.time()
    lock = threading.Lock()
    api_lock = threading.Lock()

    success_results: list[StockResult] = []
    fail_results: list[StockResult] = []
    stats: dict[str, int] = {
        "fd_inserted": 0,
        "fd_skipped": 0,
        "fd_error": 0,
        "meta_inserted": 0,
        "meta_updated": 0,
        "meta_error": 0,
    }

    progress_table = Table(
        show_header=True, header_style="bold cyan", box=None, padding=(0, 1)
    )
    progress_table.add_column("#", justify="right", width=5)
    progress_table.add_column("Ticker", width=12)
    progress_table.add_column("Currency", width=8)
    progress_table.add_column("Rows", justify="right", width=6)
    progress_table.add_column("FY Range", width=11)
    progress_table.add_column("Max FP", width=8)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_one_stock,
                ctx,
                api_lock,
                lock,
                i,
                total,
                args.quiet,
                stock,
                args.interval,
                args.dry_run,
            ): stock
            for i, stock in enumerate(stocks, 1)
        }

        for future in as_completed(futures):
            result = future.result()
            with lock:
                if result.ok:
                    success_results.append(result)
                    stats["fd_inserted"] += result.fd_inserted
                    stats["fd_skipped"] += result.fd_skipped
                    stats["fd_error"] += result.fd_error
                    if not args.dry_run:
                        stats["meta_" + result.meta_result] = (
                            stats.get("meta_" + result.meta_result, 0) + 1
                        )
                else:
                    fail_results.append(result)

                done = len(success_results) + len(fail_results)
                if not args.quiet and result.ok:
                    fy_range = f"{result.min_fy}-{result.max_fy}"
                    progress_table.add_row(
                        str(done),
                        result.ticker,
                        result.currency,
                        str(result.row_count),
                        fy_range,
                        result.max_fp,
                    )

    ctx.close()
    elapsed = time.time() - start_time

    if not args.quiet:
        success_results.sort(key=lambda r: r.ticker)
        fail_results.sort(key=lambda r: r.ticker)

        console.print(progress_table)

        summary = Table(
            title="抓取完成", show_header=True, header_style="bold", box=None
        )
        summary.add_column("项目", style="bold")
        summary.add_column("值")
        summary.add_row("成功", f"{len(success_results):,}")
        summary.add_row("失败", f"{len(fail_results):,}")
        summary.add_row(
            "字段定义",
            f"新增 {stats['fd_inserted']}  跳过 {stats['fd_skipped']}  错误 {stats['fd_error']}",
        )
        summary.add_row(
            "元数据",
            f"新增 {stats['meta_inserted']}  更新 {stats['meta_updated']}  错误 {stats['meta_error']}",
        )
        summary.add_row("耗时", f"{elapsed / 60:.1f} 分钟")
        if args.dry_run:
            summary.add_row("模式", "[yellow]DRY RUN[/yellow]")
        console.print()
        console.print(summary)

        if fail_results:
            fail_table = Table(
                title="失败列表", show_header=True, header_style="bold red", box=None
            )
            fail_table.add_column("Ticker", width=12)
            fail_table.add_column("Error")
            for r in fail_results:
                fail_table.add_row(r.ticker, r.error_msg[:60])
            console.print()
            console.print(fail_table)
    else:
        console.print(
            f"  抓取完成: {len(success_results)} 只 "
            f"(fd: +{stats['fd_inserted']} ={stats['fd_skipped']} x{stats['fd_error']} | "
            f"meta: +{stats['meta_inserted']} ~{stats['meta_updated']} x{stats['meta_error']} | "
            f"fail: {len(fail_results)} | "
            f"{elapsed / 60:.1f}m)"
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="美股财报抓取 (累计季报)")
    p.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="逗号分隔的 ticker 列表 (e.g. US.AAPL,US.MSFT)",
    )
    p.add_argument("--max-stocks", type=int, default=0, help="最多处理 N 只 (0=不限)")
    p.add_argument(
        "--workers", type=int, default=3, help="并发线程数 (默认 3, 最大 10)"
    )
    p.add_argument(
        "--interval", type=float, default=1.5, help="API 调用间隔秒数 (默认 1.5)"
    )
    p.add_argument("--dry-run", action="store_true", help="仅预览，不写库")
    p.add_argument(
        "--quiet", action="store_true", help="cron 模式: 不逐行打印, 仅输出汇总"
    )

    args = p.parse_args()

    if args.tickers and args.max_stocks:
        p.error("--tickers 和 --max-stocks 不能同时使用")
    if args.workers < 1 or args.workers > 10:
        p.error("--workers 范围 1-10")
    return args


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
