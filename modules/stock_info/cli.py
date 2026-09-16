"""港股活跃股票同步 CLI。"""

from __future__ import annotations

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
