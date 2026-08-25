"""港股日K线数据 ETL CLI。

子命令:
  download - 下载日K线数据（支持 --fetcher 选择数据源: tiger / akshare）
  upload   - 上传日K线数据到 Supabase
  check    - 检查数据质量（NR/BR 一致性等）
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

import typer

from modules.stock_price.utils import parse_tickers, resolve_rights

app = typer.Typer(help="港股日K线数据 ETL")


@app.command()
def download(
    tickers: Annotated[str, typer.Option(help="股票代码，逗号分隔")] = "",
    start_date: Annotated[datetime, typer.Option(help="起始日期")] = datetime.now(),
    end_date: Annotated[datetime, typer.Option(help="结束日期")] = datetime.now(),
    right: Annotated[Literal["NR", "BR", "both"], typer.Option(help="复权方式")] = "both",
    fetcher: Annotated[Literal["tiger", "akshare", "sina"], typer.Option(help="数据源")] = "akshare",
):
    """下载日K线数据"""
    from rich.console import Console

    from modules.stock_price.download import StockPriceDownloader, create_fetcher

    console = Console()
    ticker_list = parse_tickers(tickers)
    rights = resolve_rights(right)

    fetcher_instance = create_fetcher(fetcher)
    console.print(f"数据源: {fetcher}")
    dl = StockPriceDownloader(fetcher=fetcher_instance, console=console)
    dl.download(ticker_list, start_date.date(), end_date.date(), rights)


@app.command()
def upload(
    tickers: Annotated[str, typer.Option(help="股票代码，逗号分隔（为空则上传全部）")] = "",
    start_date: Annotated[datetime, typer.Option(help="只上传该日期之后的数据")] = datetime.now(),
    end_date: Annotated[datetime, typer.Option(help="只上传该日期之前的数据")] = datetime.now(),
    dry_run: Annotated[bool, typer.Option(help="仅打印，不实际上传")] = False,
):
    """上传日K线数据到 Supabase"""
    from rich.console import Console

    from modules.stock_price.upload import StockPriceUploader

    console = Console()
    ticker_list = parse_tickers(tickers)

    uploader = StockPriceUploader(console=console)
    results = uploader.upload(
        tickers=ticker_list,
        start_date=start_date.date(),
        end_date=end_date.date(),
        dry_run=dry_run,
    )

    failed = [r for r in results if not r.success]
    if failed:
        console.print(f"\n[red]{len(failed)} 组上传失败:[/red]")
        for r in failed:
            console.print(f"  {r.right}: {r.error}")


@app.command()
def check(
    file: Annotated[str, typer.Option(help="指定文件名（如 00837_NR.json），为空则检查全部")] = "",
):
    """检查数据质量"""
    from modules.stock_price.check import run_checks

    file_arg = file or None
    report = run_checks(file_arg=file_arg)
    if not report.ok:
        raise typer.Exit(code=1)
