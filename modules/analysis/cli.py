"""数据分析处理器 CLI。

子命令:
  daily-ranking              - 生成每日回购排行榜
  single-company-daily-summary - 单公司每日回购摘要
  abnormal-repurchase        - 回购异动
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

import typer

from modules.analysis.abnormal_repurchase import Renderer

app = typer.Typer(help="数据分析")


@app.command()
def daily_ranking(
    date: Annotated[datetime, typer.Option(help="交易日期")] = ...,
    top: Annotated[int, typer.Option(help="只显示前 N 名 (0=全部)")] = 0,
    print_table: Annotated[bool, typer.Option("--print", help="打印表格")] = False,
    data_source: Annotated[
        Literal["local", "hkex_repurchase_reports", "hkex_repurchase_realtime_reports"],
        typer.Option(help="数据来源"),
    ] = "hkex_repurchase_realtime_reports",
):
    """生成每日回购排行榜"""
    from modules.analysis.daily_ranking import DailyRanking, DataFetcher, DataSource, TerminalRenderer

    source = DataSource(data_source)
    renderer = TerminalRenderer() if print_table else None
    ranking = DailyRanking(fetcher=DataFetcher(data_source=source), renderer=renderer)
    ranking.load(date.date())

    if not ranking.items:
        print(f"{date.date()} 无回购数据")
        return

    if print_table:
        ranking.print(top_n=top)


@app.command()
def single_company_daily_summary(
    ticker: Annotated[str, typer.Option(help="股票代码 (如 00700)")] = ...,
    date: Annotated[datetime, typer.Option(help="交易日期（默认今天）")] = None,
    compact: Annotated[bool, typer.Option(help="紧凑模式输出")] = False,
):
    """单公司每日回购摘要"""
    from modules.analysis.single_company_daily_summary import Renderer, SingleCompanyDailySummary

    trade_date = (date or datetime.now()).date()

    summary = SingleCompanyDailySummary(renderer=Renderer(compact=compact))
    summary.load(ticker, trade_date)

    if not summary.data:
        print(f"{ticker} 在 {trade_date} 无回购数据")
        return

    print(summary.to_markdown())


@app.command()
def abnormal_repurchase(
    date: Annotated[datetime, typer.Option(help="交易日期（默认今天）")] = None,
    threshold: Annotated[float, typer.Option(help="占比阈值（百分比）")] = 10.0,
    limit: Annotated[int, typer.Option(help="展示条数（0=全部）")] = 100,
    compact: Annotated[bool, typer.Option(help="是否展示紧凑文本")] = False
):
    """回购异动：按回购额占成交额占比降序排序"""
    from modules.analysis.abnormal_repurchase import AbnormalRepurchase

    trade_date = (date or datetime.now()).date()

    ar = AbnormalRepurchase(renderer=Renderer(compact=compact))
    ar.load(trade_date, threshold=threshold)

    if not ar.items:
        print(f"{trade_date} 无符合条件的回购异动数据")
        return

    print(ar.to_markdown(limit=limit))
