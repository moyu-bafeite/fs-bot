"""港股活跃股票同步 CLI。"""

from __future__ import annotations

from typing import Literal

import typer
from rich.console import Console

app = typer.Typer(help="同步 HKEX 活跃股票列表")


@app.command()
def hkex_stock_data():
    """下载 HKEX 活跃股票列表，并写入数据库。"""
    from modules.stock_info.hkex_stock_data import sync

    count = sync()
    console = Console()
    console.print(f"[green]✓ 共写入 {count} 条股票记录[/green]")


@app.command()
def financial_statements(
    ticker: str = typer.Option(..., help="股票代码，如 00700 或 700"),
    doc_type: Literal["announcement", "report"] = typer.Option(
        "report", "--type", help="announcement=业绩公告 / report=年报中报"
    ),
):
    """查询指定股票的财务报表公告或业绩公告。"""
    from modules.stock_info.financial_statements import FinancialStatementHandler

    console = Console()
    handler = FinancialStatementHandler()

    try:
        result = handler.fetch(ticker, doc_type)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]请求失败: {e}[/red]")
        raise typer.Exit(1)

    handler.display(result, console)
