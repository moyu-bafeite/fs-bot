"""同步 SEC EDGAR 公司 ticker 与 CIK 映射，写入 us_sec_cik_mappings 表。"""

from __future__ import annotations

import argparse

from edgar import get_company_tickers, set_identity
from rich.console import Console
from rich.table import Table

from lib.db import upsert_cik_mappings

console = Console()


def _normalize_ticker(ticker: str) -> str:
    """标准化 ticker：添加 US. 前缀，BRK-B → BRK.B。"""
    # BRK-B → BRK.B
    ticker = ticker.replace("-", ".")
    return f"US.{ticker}"


def _format_cik(cik: int | str) -> str:
    """将 CIK 补齐为 10 位字符串。"""
    return str(cik).zfill(10)


def build_records() -> list[dict[str, str]]:
    """从 edgartools 获取 ticker-CIK 映射并构建记录。"""
    df = get_company_tickers(as_dataframe=True, clean_name=True)
    records: list[dict[str, str]] = []
    for _, row in df.iterrows():
        ticker = str(row["ticker"])
        cik = str(row["cik"])
        company = str(row["company"])
        exchange = str(row.get("exchange") or "")
        records.append(
            {
                "ticker": _normalize_ticker(ticker),
                "cik": _format_cik(cik),
                "company_name": company,
                "exchange": exchange,
            }
        )
    return records


def sync() -> int:
    """同步 CIK 映射，返回写入记录数。"""
    set_identity("Finsco support@finsco.io")

    console.print("正在从 SEC EDGAR 获取 ticker-CIK 映射...")
    records = build_records()
    console.print(f"获取到 {len(records)} 条记录")

    console.print("正在写入数据库...")
    upsert_cik_mappings(records)

    _print_summary(records)
    return len(records)


def _print_summary(records: list[dict[str, str]]) -> None:
    """打印同步结果摘要。"""
    exchanges: dict[str, int] = {}
    for r in records:
        ex = r["exchange"] or "Unknown"
        exchanges[ex] = exchanges.get(ex, 0) + 1

    table = Table(title="CIK 映射同步结果")
    table.add_column("指标", style="cyan")
    table.add_column("数量", style="green", justify="right")
    table.add_row("总计", str(len(records)))
    for ex, count in sorted(exchanges.items(), key=lambda x: -x[1]):
        table.add_row(ex, str(count))
    console.print(table)

    # 显示示例
    example_table = Table(title="示例数据")
    example_table.add_column("Ticker", style="cyan")
    example_table.add_column("CIK", style="green")
    example_table.add_column("公司", style="white")
    for r in records[:5]:
        example_table.add_row(r["ticker"], r["cik"], r["company_name"])
    console.print(example_table)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="同步 SEC EDGAR ticker-CIK 映射")
    return p.parse_args()


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    sync()


if __name__ == "__main__":
    main()
