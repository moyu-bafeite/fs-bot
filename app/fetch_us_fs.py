#!/usr/bin/env python3
"""从 Futu API 抓取美股财报数据，写入 data/ 目录。

单线程串行 + pyrate-limiter 限流（1次/秒，滑动窗口内不超30次/30秒）。
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import futu as ft
from pyrate_limiter import Duration, Limiter, Rate
from rich.console import Console
from rich.table import Table

from lib.db import get_pending_stocks, get_stocks_by_tickers

console = Console()

F10_TO_PERIOD = {
    1: "q1",
    5: "h1",
    6: "9m",
    7: "annual",
}

BS_FTYPE_TO_PERIOD = {
    1: "q1",
    2: "h1",
    3: "9m",
    4: "annual",
}


@dataclass
class FetchResult:
    ticker: str
    ok: bool = False
    partial: bool = False
    warnings: list[str] = field(default_factory=list)
    item_count: int = 0
    file_count: int = 0
    error_msg: str = ""


def get_stock_list(args: argparse.Namespace) -> list[dict]:
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        stocks = get_stocks_by_tickers(tickers)
        found = {s["ticker"] for s in stocks}
        for t in tickers:
            if t not in found:
                console.print(
                    f"  [yellow]ticker 不在 us_active_stocks 表中: {t}[/yellow]"
                )
        return stocks
    return get_pending_stocks()


def _fetch_one_statement(
    ctx: ft.OpenQuoteContext,
    ticker: str,
    limiter: Limiter,
    st_type: int,
    st_key: str,
    fin_type: int,
) -> tuple[list[tuple[str, dict]], list[str]]:
    """抓取单种报表的全部分页数据。"""
    tagged: list[tuple[str, dict]] = []
    warnings: list[str] = []
    next_key = None
    while True:
        limiter.try_acquire("futu-api")
        ret, data = ctx.get_financials_statements(
            ticker,
            statement_type=st_type,
            financial_type=fin_type,
            num=50,
            next_key=next_key,
        )
        if ret != ft.RET_OK:
            warnings.append(
                f"{st_key}(st={st_type},ft={fin_type}) API 错误: "
                f"{getattr(data, 'str', data)}"
            )
            break
        for report in data.get("report_list", []):
            tagged.append((st_key, report))
        next_key = data.get("next_key")
        if not next_key or next_key == "-1":
            break
    return tagged, warnings


def fetch_reports(
    ctx: ft.OpenQuoteContext,
    ticker: str,
    limiter: Limiter,
) -> tuple[list[tuple[str, dict]], list[str]]:
    """抓取单只股票的所有报表（串行）。"""
    income, w1 = _fetch_one_statement(ctx, ticker, limiter, 1, "income", 11)
    balance, w2 = _fetch_one_statement(ctx, ticker, limiter, 2, "balance_sheet", 9)
    cashflow, w3 = _fetch_one_statement(ctx, ticker, limiter, 3, "cash_flow", 11)
    return income + balance + cashflow, w1 + w2 + w3


def write_period_file(
    path: Path, items: list[dict], field_defs: dict[str, dict]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"items": items, "field_defs": field_defs}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def fetch_one_ticker(
    ctx: ft.OpenQuoteContext,
    limiter: Limiter,
    idx: int,
    total: int,
    quiet: bool,
    ticker: str,
    data_dir: Path,
) -> FetchResult:
    """抓取单只股票，写入 data/[ticker]/ 目录。"""
    result = FetchResult(ticker=ticker)
    ticker_dir = data_dir / ticker

    if not quiet:
        console.print(f"  [{idx:>4d}/{total}] {ticker} - 开始抓取...")

    try:
        tagged, warnings = fetch_reports(ctx, ticker, limiter)
        result.warnings = warnings

        if not tagged:
            raise ValueError("无数据")

        if warnings:
            result.partial = True
            if not quiet:
                for w in warnings:
                    console.print(
                        f"  [{idx:>4d}/{total}] {ticker} - [yellow]WARN[/yellow] {w}"
                    )

        # 按 (fiscal_year, fiscal_period) 分组写入文件
        grouped: dict[tuple[int, str], list[dict]] = {}
        statements_seen: set[str] = set()
        for st_key, report in tagged:
            fy = report.get("fiscal_year")
            if not fy:
                continue
            ftype = report.get("financial_type", 10)
            period = (
                BS_FTYPE_TO_PERIOD.get(ftype, "annual")
                if st_key == "balance_sheet"
                else F10_TO_PERIOD.get(ftype, "annual")
            )
            key = (fy, period)
            if key not in grouped:
                grouped[key] = []
            for item in report.get("item_list", []):
                fid = item.get("field_id")
                if fid is None:
                    continue
                grouped[key].append(
                    {
                        "fiscal_year": fy,
                        "fiscal_period": period,
                        "statement": st_key,
                        "field_id": fid,
                        "value": float(item.get("data", 0.0)),
                    }
                )
                if item.get("display_name"):
                    statements_seen.add(st_key)

        for (fy, period), items in grouped.items():
            field_defs: dict[str, dict] = {}
            for orig_st, orig_report in tagged:
                for orig_item in orig_report.get("item_list", []):
                    dn = orig_item.get("display_name", "")
                    fid = orig_item.get("field_id")
                    if fid and dn:
                        field_defs[f"{fid}:{orig_st}"] = {"en": dn}
            write_period_file(
                ticker_dir / str(fy) / f"{period}.json", items, field_defs
            )
            result.item_count += len(items)
            result.file_count += 1

        # _meta.json
        currency = "USD"
        for _, r in tagged:
            cc = r.get("currency_code")
            if cc:
                currency = cc
                break
        ticker_dir.mkdir(parents=True, exist_ok=True)
        meta = {"currency": currency, "statements": sorted(statements_seen)}
        (ticker_dir / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False))

        result.ok = True

    except Exception as e:
        result.error_msg = str(e)

    if not quiet:
        if result.ok:
            console.print(
                f"  [{idx:>4d}/{total}] {ticker} - "
                f"{result.item_count} items, {result.file_count} files [green]OK[/green]"
            )
        else:
            console.print(
                f"  [{idx:>4d}/{total}] {ticker} - [red]FAIL[/red] {result.error_msg[:80]}"
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

    console.print(f"  待处理: {total} 只")

    try:
        ctx = ft.OpenQuoteContext(host="127.0.0.1", port=11111)
    except Exception as e:
        console.print(f"  [red]连接 FutuOpenD 失败: {e}[/red]")
        return
    console.print("  已连接 FutuOpenD\n")

    run_start = datetime.now()
    start_time = time.time()
    limiter = Limiter(Rate(1, Duration.SECOND))
    data_dir = Path(args.data_dir)

    success_results: list[FetchResult] = []
    fail_results: list[FetchResult] = []

    progress_table = Table(
        show_header=True, header_style="bold cyan", box=None, padding=(0, 1)
    )
    progress_table.add_column("#", justify="right", width=5)
    progress_table.add_column("Ticker", width=12)
    progress_table.add_column("Items", justify="right", width=8)
    progress_table.add_column("Files", justify="right", width=6)

    for i, stock in enumerate(stocks, 1):
        result = fetch_one_ticker(
            ctx, limiter, i, total, args.quiet, stock["ticker"], data_dir
        )
        if result.ok:
            success_results.append(result)
        else:
            fail_results.append(result)

        if not args.quiet and result.ok:
            progress_table.add_row(
                str(len(success_results) + len(fail_results)),
                result.ticker,
                str(result.item_count),
                str(result.file_count),
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
        summary.add_row("总 items", f"{sum(r.item_count for r in success_results):,}")
        summary.add_row("总 files", f"{sum(r.file_count for r in success_results):,}")
        summary.add_row("耗时", f"{elapsed / 60:.1f} 分钟")
        console.print()
        console.print(summary)

        if fail_results:
            fail_table = Table(
                title="失败列表", show_header=True, header_style="bold red", box=None
            )
            fail_table.add_column("Ticker", width=12)
            fail_table.add_column("Error")
            for r in fail_results:
                fail_table.add_row(r.ticker, r.error_msg[:80])
            console.print()
            console.print(fail_table)

        partial = [r for r in success_results if r.partial]
        if partial:
            partial_table = Table(
                title="部分数据告警",
                show_header=True,
                header_style="bold yellow",
                box=None,
            )
            partial_table.add_column("Ticker", width=12)
            partial_table.add_column("Warnings")
            for r in partial:
                partial_table.add_row(r.ticker, "; ".join(r.warnings))
            console.print()
            console.print(partial_table)
    else:
        console.print(
            f"  抓取完成: {len(success_results)} ok, {len(fail_results)} fail, "
            f"{sum(r.item_count for r in success_results)} items, "
            f"{elapsed / 60:.1f}m"
        )

    # 日志
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = run_start.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"fetch_us_fs_{ts}.json"
    log_data = {
        "run_at": run_start.isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "summary": {
            "total": total,
            "success": len(success_results),
            "fail": len(fail_results),
            "partial": sum(1 for r in success_results if r.partial),
        },
        "fail_list": [
            {"ticker": r.ticker, "error": r.error_msg}
            for r in sorted(fail_results, key=lambda r: r.ticker)
        ],
    }
    log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2))
    if not args.quiet:
        console.print(f"\n  日志已写入: {log_path}")
    else:
        console.print(f"  日志: {log_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="从 Futu API 抓取美股财报数据")
    p.add_argument("--tickers", type=str, default=None, help="逗号分隔的 ticker 列表")
    p.add_argument("--max-stocks", type=int, default=0, help="最多处理 N 只 (0=不限)")
    p.add_argument("--data-dir", type=str, default="data", help="数据目录 (默认 data/)")
    p.add_argument("--quiet", action="store_true", help="cron 模式")
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
