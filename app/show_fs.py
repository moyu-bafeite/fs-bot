"""从 us_fs_items 查询并打印某公司财报（rich 表格，列是年份）。"""

from __future__ import annotations

import argparse

from rich import box
from rich.console import Console
from rich.table import Table

from lib.db import get_fs_items

console = Console()

VALID_TYPES = {"q1", "h1", "9m", "annual"}
VALID_STATEMENTS = {"income", "balance_sheet", "cash_flow"}


def _parse_years(raw: str) -> list[int]:
    """解析年份参数：'2022,2023' 或 '2022-2024'。"""
    if "-" in raw:
        parts = raw.split("-", 1)
        return list(range(int(parts[0]), int(parts[1]) + 1))
    return [int(y.strip()) for y in raw.split(",") if y.strip()]


def _fmt_value(v: float) -> str:
    """格式化数值：大数千分位，小数保留 2 位。"""
    if abs(v) >= 1_000_000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:,.2f}"
    return f"{v:.4f}"


def show(args: argparse.Namespace) -> None:
    years = _parse_years(args.years)

    rows = get_fs_items(
        ticker=args.ticker.upper(),
        fiscal_years=years,
        fiscal_period=args.type,
        statement=args.statement,
    )

    if not rows:
        console.print(f"  [yellow]未找到 {args.ticker} 的财报数据[/yellow]")
        return

    # 按 statement 分组，保持声明顺序
    stmt_order = ["income", "balance_sheet", "cash_flow"]
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["statement"], []).append(r)
    ordered_stmts = [s for s in stmt_order if s in grouped]

    # 构建单一表格
    title = args.ticker.upper()
    table = Table(title=title, show_header=True, header_style="bold cyan", box=box.ROUNDED)
    table.add_column("报表 / 字段", style="bold", min_width=30)
    for y in years:
        table.add_column(str(y), justify="right", min_width=14)

    total_rows = 0
    for i, stmt in enumerate(ordered_stmts):
        stmt_rows = grouped[stmt]

        # 分隔行（非首个报表前）
        if i > 0:
            table.add_row(*["─" * 30] + ["─" * 14] * len(years), style="dim")

        # 报表标题行
        stmt_label = {"income": "利润表", "balance_sheet": "资产负债表", "cash_flow": "现金流量表"}
        table.add_row(
            f"[bold white]{stmt_label.get(stmt, stmt)}[/bold white]",
            *[""] * len(years),
        )

        # pivot：field_id -> {year -> value}
        field_years: dict[int, dict[int, float]] = {}
        field_names: dict[int, str] = {}
        for r in stmt_rows:
            fid = r["field_id"]
            fy = r["fiscal_year"]
            field_years.setdefault(fid, {})[fy] = r["value"]
            dn = r.get("display_name")
            if dn:
                if isinstance(dn, dict):
                    field_names[fid] = dn.get("en", str(fid))
                else:
                    field_names[fid] = str(dn)

        sorted_fids = sorted(field_years.keys())

        # 合并 - 开头的字段到最近的非 - 字段（仅视觉分组，不累加数值）
        merged: list[tuple[str, dict[int, float], list[tuple[str, dict[int, float]]]]] = []
        for fid in sorted_fids:
            name = field_names.get(fid, str(fid))
            yv = field_years[fid]
            if name.startswith("-") and merged:
                merged[-1][2].append((name, dict(yv)))
            else:
                merged.append((name, dict(yv), []))

        for parent_name, parent_yv, children in merged:
            vals = []
            for y in years:
                v = parent_yv.get(y)
                vals.append(_fmt_value(v) if v is not None else "-")
            table.add_row(parent_name, *vals)
            total_rows += 1
            for child_name, child_yv in children:
                cvals = []
                for y in years:
                    cv = child_yv.get(y)
                    cvals.append(_fmt_value(cv) if cv is not None else "-")
                table.add_row("  " + child_name, *cvals)
                total_rows += 1

    console.print()
    console.print(table)
    console.print(f"\n  共 {total_rows} 条记录")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="打印美股财报数据")
    p.add_argument("--ticker", required=True, help="股票代码 (e.g. US.AAPL)")
    p.add_argument("--years", required=True, help="年份: 2022,2023 或 2022-2024")
    p.add_argument(
        "--type",
        required=True,
        choices=sorted(VALID_TYPES),
        help="报告期类型",
    )
    p.add_argument(
        "--statement",
        choices=sorted(VALID_STATEMENTS),
        default=None,
        help="报表类型过滤 (默认全部)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    show(args)
