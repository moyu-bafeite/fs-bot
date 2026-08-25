"""数据分析处理器 CLI。

子命令:
  daily-ranking              - 生成每日回购排行榜
  single-company-daily-summary - 单公司每日回购摘要
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

import typer

app = typer.Typer(help="数据分析")


@app.command()
def daily_ranking(
    date: Annotated[datetime, typer.Option(help="交易日期")] = ...,
    top: Annotated[int, typer.Option(help="只显示前 N 名 (0=全部)")] = 0,
    format: Annotated[Literal["table", "json", "csv"], typer.Option(help="输出格式")] = "table",
    data_source: Annotated[
        Literal["local", "hkex_repurchase_reports", "hkex_repurchase_realtime_reports"],
        typer.Option(help="数据来源"),
    ] = "hkex_repurchase_realtime_reports",
):
    """生成每日回购排行榜。"""
    from modules.analysis.daily_ranking import DailyRanking, DataFetcher, DataSource

    source = DataSource(data_source)
    ranking = DailyRanking(fetcher=DataFetcher(data_source=source))
    ranking.load(date.date())

    if not ranking.items:
        print(f"{date.date()} 无回购数据")
        return

    if format == "table":
        ranking.print(top_n=top)
    elif format == "json":
        print(ranking.to_json(top_n=top))
    elif format == "csv":
        print(ranking.to_csv(top_n=top))


@app.command()
def single_company_daily_summary(
    ticker: Annotated[str, typer.Option(help="股票代码 (如 00700)")] = ...,
    date: Annotated[datetime, typer.Option(help="交易日期（默认今天）")] = None,
    output: Annotated[str, typer.Option(help="输出 Markdown 文件路径")] = "",
):
    """单公司每日回购摘要。"""
    from modules.analysis.single_company_daily_summary import SingleCompanyDailySummary

    trade_date = (date or datetime.now()).date()

    summary = SingleCompanyDailySummary()
    summary.load(ticker, trade_date)

    if not summary.data:
        print(f"{ticker} 在 {trade_date} 无回购数据")
        return

    md = summary.to_markdown()

    if output:
        from pathlib import Path

        Path(output).write_text(md, encoding="utf-8")
        print(f"已写入: {output}")
    else:
        print(md)
