#!/usr/bin/env python3
"""从 Futu API 抓取港股回购数据，写入 data/repurchase_actions/ 目录。

单线程串行 + pyrate-limiter 限流（1次/秒，滑动窗口内不超30次/30秒）。
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import futu as ft
from pyrate_limiter import Duration, Limiter, Rate
from rich.console import Console
from rich.table import Table

from lib.db import get_hk_stock_by_code, get_hk_stocks

console = Console()


def _clean_nan(value):
    """将 NaN/Inf 值转换为 None，其他值保持不变。"""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


@dataclass
class FetchResult:
    stock_code: str
    ok: bool = False
    record_count: int = 0
    error_msg: str = ""


def get_stock_list(args: argparse.Namespace) -> list[dict]:
    if args.stock_codes:
        codes = [c.strip() for c in args.stock_codes.split(",") if c.strip()]
        stocks = []
        for code in codes:
            stock = get_hk_stock_by_code(code)
            if stock:
                stocks.append(stock)
            else:
                console.print(f"  [yellow]stock_code 不在 sehk_active_stocks 表中: {code}[/yellow]")
        return stocks
    return get_hk_stocks()


def fetch_one_stock(
    ctx: ft.OpenQuoteContext,
    limiter: Limiter,
    idx: int,
    total: int,
    quiet: bool,
    stock: dict,
    data_dir: Path,
) -> FetchResult:
    """抓取单只股票的回购记录，写入 data/repurchase_actions/[stock_code].json。"""
    stock_code = stock["stock_code"]
    result = FetchResult(stock_code=stock_code)

    if not quiet:
        console.print(f"  [{idx:>4d}/{total}] {stock_code} - 开始抓取...")

    try:
        records: list[dict] = []
        next_key = None

        while True:
            limiter.try_acquire("futu-api")
            ret, data = ctx.get_corporate_actions_buybacks(
                f"HK.{stock_code}", num=50, next_key=next_key
            )
            if ret != ft.RET_OK:
                raise RuntimeError(str(data))

            if not isinstance(data, dict):
                raise RuntimeError(f"API 返回异常: type={type(data)}, value={str(data)[:200]}")

            # hk_buy_back_list 是 DataFrame，需要转换为 list[dict]
            buy_back_df = data.get("hk_buy_back_list")
            if buy_back_df is not None and hasattr(buy_back_df, "to_dict"):
                buy_back_list = buy_back_df.to_dict("records")
            else:
                buy_back_list = buy_back_df or []

            for item in buy_back_list:
                records.append({
                    "stock_code": stock_code,
                    "publish_date": _clean_nan(item.get("publ_date_str")),
                    "end_date": _clean_nan(item.get("end_date_str")),
                    "amount": _clean_nan(item.get("buy_back_money")),
                    "quantity": _clean_nan(item.get("buy_back_sum")),
                    "percentage": _clean_nan(item.get("percentage")),
                    "high_price": _clean_nan(item.get("high_price")),
                    "low_price": _clean_nan(item.get("low_price")),
                    "cumulative_quantity": _clean_nan(item.get("cumulative_sum")),
                    "cumulative_percentage": _clean_nan(item.get("cumulative_percentage")),
                    "share_type": _clean_nan(item.get("share_type")) or "普通股",
                })

            next_key = data.get("next_key")
            if not next_key or next_key == "-1":
                break

        # 写入文件
        file_path = data_dir / f"{stock_code}.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(records, ensure_ascii=False, indent=2))

        result.record_count = len(records)
        result.ok = True

    except Exception as e:
        result.error_msg = str(e)

    if not quiet:
        if result.ok:
            console.print(
                f"  [{idx:>4d}/{total}] {stock_code} - "
                f"{result.record_count} records [green]OK[/green]"
            )
        else:
            console.print(
                f"  [{idx:>4d}/{total}] {stock_code} - [red]FAIL[/red] {result.error_msg[:80]}"
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

    for i, stock in enumerate(stocks, 1):
        result = fetch_one_stock(
            ctx, limiter, i, total, args.quiet, stock, data_dir
        )
        if result.ok:
            success_results.append(result)
        else:
            fail_results.append(result)

    ctx.close()
    elapsed = time.time() - start_time

    if not args.quiet:
        success_results.sort(key=lambda r: r.stock_code)
        fail_results.sort(key=lambda r: r.stock_code)

        summary = Table(
            title="抓取完成", show_header=True, header_style="bold", box=None
        )
        summary.add_column("项目", style="bold")
        summary.add_column("值")
        summary.add_row("成功", f"{len(success_results):,}")
        summary.add_row("失败", f"{len(fail_results):,}")
        summary.add_row("总记录", f"{sum(r.record_count for r in success_results):,}")
        summary.add_row("耗时", f"{elapsed / 60:.1f} 分钟")
        console.print()
        console.print(summary)

        if fail_results:
            fail_table = Table(
                title="失败列表", show_header=True, header_style="bold red", box=None
            )
            fail_table.add_column("Stock Code", width=12)
            fail_table.add_column("Error")
            for r in fail_results:
                fail_table.add_row(r.stock_code, r.error_msg[:80])
            console.print()
            console.print(fail_table)
    else:
        console.print(
            f"  抓取完成: {len(success_results)} ok, {len(fail_results)} fail, "
            f"{sum(r.record_count for r in success_results)} records, "
            f"{elapsed / 60:.1f}m"
        )

    # 日志
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = run_start.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"fetch_hk_repurchase_{ts}.json"
    log_data = {
        "run_at": run_start.isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "summary": {
            "total": total,
            "success": len(success_results),
            "fail": len(fail_results),
        },
        "fail_list": [
            {"stock_code": r.stock_code, "error": r.error_msg}
            for r in sorted(fail_results, key=lambda r: r.stock_code)
        ],
    }
    log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2))
    if not args.quiet:
        console.print(f"\n  日志已写入: {log_path}")
    else:
        console.print(f"  日志: {log_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="从 Futu API 抓取港股回购数据")
    p.add_argument("--stock-codes", type=str, default=None, help="逗号分隔的 stock_code 列表")
    p.add_argument("--max-stocks", type=int, default=0, help="最多处理 N 只 (0=不限)")
    p.add_argument("--data-dir", type=str, default="data/repurchase_actions", help="数据目录 (默认 data/repurchase_actions/)")
    p.add_argument("--quiet", action="store_true", help="cron 模式")
    args = p.parse_args()
    if args.stock_codes and args.max_stocks:
        p.error("--stock-codes 和 --max-stocks 不能同时使用")
    return args


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
