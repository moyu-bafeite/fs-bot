#!/usr/bin/env python3
"""从 us_sec_form4_filing_transactions 聚合交易类型，写入 us_sec_form4_transaction_definitions。

可重复运行，ON CONFLICT 更新。
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from lib.db import get_distinct_form4_defs, upsert_form4_definitions

console = Console()


def run(args: argparse.Namespace) -> None:
    console.print("  查询去重交易类型...")
    defs = get_distinct_form4_defs()

    if not defs:
        console.print("  无数据，请先运行 fetch + push")
        return

    console.print(f"  发现 {len(defs)} 种交易类型")

    # upsert 定义表
    upsert_form4_definitions(defs)

    # 打印结果
    table = Table(title="Form 4 交易类型定义", show_header=True, header_style="bold")
    table.add_column("transaction_type", style="cyan")
    table.add_column("code", style="yellow")
    table.add_column("security_type")
    table.add_column("code_description")

    for d in sorted(
        defs, key=lambda x: (x["security_type"], x["transaction_type"], x["code"])
    ):
        table.add_row(
            d["transaction_type"],
            d["code"],
            d["security_type"],
            d.get("code_description") or "",
        )

    console.print()
    console.print(table)
    console.print(f"\n  已写入 us_sec_form4_transaction_definitions ({len(defs)} 条)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="聚合 Form 4 交易类型定义表")
    return p.parse_args()


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
