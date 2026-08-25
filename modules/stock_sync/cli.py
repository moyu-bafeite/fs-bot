"""港股活跃股票同步 CLI。"""

from __future__ import annotations

import typer

app = typer.Typer(help="同步 HKEX 活跃股票列表")


@app.command()
def sync():
    """下载 HKEX 活跃股票列表并写入数据库"""
    from modules.stock_sync.sync import sync as do_sync

    count = do_sync()
    print(f"完成，共写入 {count} 条股票记录")
