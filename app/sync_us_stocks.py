"""通过 Futu OpenD API 爬取美股市场未退市正股，写入 us_active_stocks 表。"""

from __future__ import annotations

import argparse
import os
import time

from futu import RET_OK, Market, OpenQuoteContext, SecurityType
from rich.console import Console
from rich.progress import track
from rich.table import Table

from lib.db import (
    get_existing_us_tickers,
    update_us_stock_profile,
    upsert_us_stocks,
)

console = Console()


def build_arg_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(description="同步美股活跃股票列表")
    parser.add_argument(
        "--full",
        action="store_true",
        help="全量模式：对所有股票获取公司概况（默认仅新增股票）",
    )
    return parser


def _parse_fiscal_date(date_str: str) -> tuple[int, int]:
    """解析年结日字符串（如 '12-31'）为 (month, day)。"""
    parts = date_str.strip().split("-")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return 12, 31


def _fetch_company_profile(
    quote_ctx: OpenQuoteContext, code: str
) -> tuple[str | None, int, int]:
    """获取单只股票的公司概况，返回 (sector, fiscal_month, fiscal_day)。"""
    ret, data = quote_ctx.get_company_profile(code)
    if ret != RET_OK:
        return None, 12, 31

    sector: str | None = None
    fiscal_month = 12
    fiscal_day = 31

    for _, row in data.iterrows():
        name = row["name"]
        value = row["value"]
        if name == "所属市场":
            # 所属市场不是 sector，但暂无更好的 sector 来源
            pass
        elif name == "年结日" and value:
            fiscal_month, fiscal_day = _parse_fiscal_date(value)

    return sector, fiscal_month, fiscal_day


def sync(full: bool = False) -> int:
    """同步美股列表，返回写入记录数。

    Args:
        full: True 时对所有股票调用 get_company_profile；False 仅对新增股票调用。
    """
    host = os.environ.get("FUTU_OPEND_HOST", "127.0.0.1")
    port = int(os.environ.get("FUTU_OPEND_PORT", "11111"))

    console.print(f"连接 Futu OpenD ({host}:{port})...")

    with OpenQuoteContext(host=host, port=port) as quote_ctx:
        # 1. 获取全量美股静态数据
        console.print("正在获取美股静态数据...")
        ret, data = quote_ctx.get_stock_basicinfo(Market.US, SecurityType.STOCK)
        if ret != RET_OK:
            raise RuntimeError(f"Futu API error: {data}")

        console.print(f"API 返回 {len(data)} 条记录，过滤退市股票...")

        # 2. 过滤退市股，构建记录
        all_records: list[dict] = []
        for _, row in data.iterrows():
            if row["delisting"]:
                continue
            listing_date = row.get("listing_date") or None
            if listing_date == "":
                listing_date = None
            all_records.append(
                {
                    "ticker": row["code"],
                    "company_name": row["name"],
                    "market": "US",
                    "listing_date": listing_date,
                    "futu_id": int(row["stock_id"]),
                }
            )

        console.print(f"过滤后剩余 {len(all_records)} 只未退市正股")

        # 3. 查询已有记录，判断新增
        existing_tickers = get_existing_us_tickers()
        new_tickers = {r["ticker"] for r in all_records} - existing_tickers
        console.print(f"已有 {len(existing_tickers)} 只，新增 {len(new_tickers)} 只")

        # 4. Upsert 全部基础数据
        upsert_us_stocks(all_records)

        # 5. 确定需要 profile 的列表
        if full:
            tickers_for_profile = [r["ticker"] for r in all_records]
            console.print(
                f"[bold]全量模式[/bold]：将为所有 {len(tickers_for_profile)} 只股票获取公司概况..."
            )
        else:
            tickers_for_profile = sorted(new_tickers)
            if not tickers_for_profile:
                console.print("[green]无新增股票，跳过公司概况获取[/green]")
                _print_summary(all_records, len(new_tickers), 0)
                return len(all_records)
            console.print(
                f"[bold]增量模式[/bold]：将为 {len(tickers_for_profile)} 只新增股票获取公司概况..."
            )

        # 6. 逐个调用 get_company_profile
        updated = 0
        failed: list[str] = []
        for ticker in track(tickers_for_profile, description="获取公司概况..."):
            try:
                sector, fiscal_month, fiscal_day = _fetch_company_profile(
                    quote_ctx, ticker
                )
                update_us_stock_profile(ticker, sector, fiscal_month, fiscal_day)
                updated += 1
            except Exception as e:  # noqa: BLE001
                failed.append(f"{ticker} ({e})")
            # rate limit: 30次/30秒
            time.sleep(1.1)

    _print_summary(all_records, len(new_tickers), updated, failed)
    return len(all_records)


def _print_summary(
    records: list[dict],
    new_count: int,
    profile_updated: int,
    failed: list[str],
) -> None:
    """打印同步结果摘要。"""
    table = Table(title="美股同步结果")
    table.add_column("指标", style="cyan")
    table.add_column("数量", style="green", justify="right")
    table.add_row("未退市正股总数", str(len(records)))
    table.add_row("新增写入", str(new_count))
    table.add_row("公司概况更新", str(profile_updated))
    table.add_row("失败", str(len(failed)), style="red" if failed else "green")
    console.print(table)

    if failed:
        fail_table = Table(title="失败列表")
        fail_table.add_column("序号", style="dim", justify="right")
        fail_table.add_column("Ticker / 错误", style="red")
        for i, item in enumerate(failed, 1):
            fail_table.add_row(str(i), item)
        console.print(fail_table)
