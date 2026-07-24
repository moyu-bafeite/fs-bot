#!/usr/bin/env python3
"""美股财报原始数据抓取脚本（行式存储 / cronjob 友好）。"""

from __future__ import annotations

import argparse
import time
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
    (1, "income"),
    (2, "balance_sheet"),
    (3, "cash_flow"),
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

FTYPES_MUL_QUARTERLY = [11]


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
    financial_types: list[int],
    statement_filter: set[str] | None,
    interval: float,
) -> list[tuple[str, dict]] | None:
    tagged: list[tuple[str, dict]] = []
    st_config = [
        (t, k)
        for t, k in STATEMENT_CONFIG
        if statement_filter is None or k in statement_filter
    ]

    for st_type, st_key in st_config:
        for fin_type in financial_types:
            next_key = None
            while True:
                try:
                    ret, data = ctx.get_financials_statements(
                        ticker,
                        statement_type=st_type,
                        financial_type=fin_type,
                        num=20,
                        next_key=next_key,
                    )
                except Exception as e:
                    console.print(
                        f"  [yellow]Futu API 异常 ({ticker} {st_key} type={fin_type}): {e}[/yellow]"
                    )
                    break
                if ret != ft.RET_OK:
                    break
                for report in data.get("report_list", []):
                    tagged.append((st_key, report))
                next_key = data.get("next_key")
                if not next_key or next_key == "-1":
                    break
                time.sleep(interval)
        time.sleep(interval)

    return tagged if tagged else None


def reports_to_rows(tagged: list[tuple[str, dict]]) -> list[dict]:
    rows: list[dict] = []
    for st_key, report in tagged:
        fy = report.get("fiscal_year")
        if not fy:
            continue
        ftype = report.get("financial_type", 10)
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


def run(args: argparse.Namespace) -> None:
    stocks = get_stock_list(args)
    total = len(stocks)
    if args.max_stocks and args.max_stocks > 0:
        stocks = stocks[: args.max_stocks]
        total = len(stocks)

    if total == 0:
        console.print("  无待处理股票")
        return

    console.print(f"  待处理: {total} 只")

    try:
        ctx = ft.OpenQuoteContext(host="127.0.0.1", port=11111)
    except Exception as e:
        console.print(f"  [red]连接 FutuOpenD 失败: {e}[/red]")
        return
    console.print("  已连接 FutuOpenD\n")

    stmt_filter = None
    if args.statements and args.statements != "all":
        stmt_filter = {s.strip() for s in args.statements.split(",")}

    ok_count = 0
    fail_count = 0
    start_time = time.time()
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
    progress_table.add_column("Status", width=8)

    for i, stock in enumerate(stocks, 1):
        ticker = stock["ticker"]

        tagged = fetch_reports(
            ctx, ticker, FTYPES_MUL_QUARTERLY, stmt_filter, args.interval
        )

        if not tagged:
            fail_count += 1
            if not args.quiet:
                progress_table.add_row(
                    str(i), ticker, "-", "-", "-", "-", "[red]无数据[/red]"
                )
            continue

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

        row_count = 0
        if not args.dry_run:
            row_count = insert_financial_items(rows)

            stock_fd: dict[tuple[int, str], dict] = {}
            for st_key, report in tagged:
                for item in report.get("item_list", []):
                    fid = item.get("field_id")
                    dn = item.get("display_name", "")
                    if fid and dn:
                        stock_fd.setdefault((fid, st_key), {"en": dn})

            fd_stats = upsert_field_defs_batch(stock_fd)
            for k in ("inserted", "skipped", "error"):
                stats["fd_" + k] = stats.get("fd_" + k, 0) + fd_stats.get(k, 0)

            if fd_stats.get("skipped", 0) > 0:
                check_field_def_conflicts(stock_fd)

            result = upsert_us_fs_metadata(ticker, currency, min_fy, max_fy, max_fp)
            stats["meta_" + result] = stats.get("meta_" + result, 0) + 1

        if row_count > 0 or args.dry_run:
            ok_count += 1
            status = "[green]OK[/green]"
        else:
            fail_count += 1
            status = "[red]FAIL[/red]"

        fy_range = f"{min_fy}-{max_fy}"
        if not args.quiet:
            progress_table.add_row(
                str(i), ticker, currency, str(len(rows)), fy_range, max_fp, status
            )

    ctx.close()

    if not args.quiet:
        console.print(progress_table)

    elapsed = time.time() - start_time

    if args.quiet:
        console.print(
            f"  抓取完成: {ok_count} 只 "
            f"(fd: +{stats['fd_inserted']} ={stats['fd_skipped']} x{stats['fd_error']} | "
            f"meta: +{stats['meta_inserted']} ~{stats['meta_updated']} x{stats['meta_error']} | "
            f"{elapsed / 60:.1f}m)"
        )
    else:
        summary = Table(
            title="抓取完成", show_header=True, header_style="bold", box=None
        )
        summary.add_column("项目", style="bold")
        summary.add_column("值")
        summary.add_row("成功", f"{ok_count:,}")
        summary.add_row("失败", f"{fail_count:,}")
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="美股财报抓取 (累计季报)")
    p.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="逗号分隔的 ticker 列表 (e.g. AAPL,MSFT)",
    )
    p.add_argument("--max-stocks", type=int, default=0, help="最多处理 N 只 (0=不限)")
    p.add_argument(
        "--statements",
        type=str,
        default="all",
        help="逗号分隔: income,balance_sheet,cash_flow (默认 all)",
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
    return args


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
