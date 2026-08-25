"""数据分析处理器 CLI。

子命令:
  daily-ranking          - 生成每日回购排行榜
  single-company-daily-summary - 单公司每日回购摘要
"""

from __future__ import annotations

import argparse
import sys
from datetime import date


def register(subparsers) -> None:
    p = subparsers.add_parser("analysis", help="数据分析")
    sub = p.add_subparsers(dest="analysis_command")

    dr = sub.add_parser("daily-ranking", help="生成每日回购排行榜")
    dr.add_argument("--date", type=str, required=True, help="交易日期 (YYYY-MM-DD)")
    dr.add_argument("--top", type=int, default=0, help="只显示前 N 名 (0=全部)")
    dr.add_argument(
        "--format", choices=["table", "json", "csv"], default="table", help="输出格式"
    )
    dr.add_argument(
        "--data-source",
        choices=["local", "hkex_repurchase_reports", "hkex_repurchase_realtime_reports"],
        default="hkex_repurchase_reports",
        help="数据来源",
    )

    sc = sub.add_parser("single-company-daily-summary", help="单公司每日回购摘要")
    sc.add_argument("--ticker", type=str, required=True, help="股票代码 (如 00700)")
    sc.add_argument("--date", type=str, default=None, help="交易日期 (YYYY-MM-DD，默认今天)")
    sc.add_argument("--output", type=str, default=None, help="输出 Markdown 文件路径（不指定则打印到终端）")

    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    cmd = getattr(args, "analysis_command", None)
    if cmd == "daily-ranking":
        _run_daily_ranking(args)
    elif cmd == "single-company-daily-summary":
        _run_single_company_summary(args)
    else:
        sys.argv = ["analysis", "--help"]
        p = argparse.ArgumentParser(description="数据分析")
        sub = p.add_subparsers(dest="cmd")
        sub.add_parser("daily-ranking")
        sub.add_parser("single-company-daily-summary")
        p.parse_args(["--help"])


def _run_daily_ranking(args: argparse.Namespace) -> None:
    from modules.analysis.daily_ranking import DailyRanking, DataFetcher, DataSource

    try:
        transaction_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"错误：日期格式无效 '{args.date}'，应为 YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    source = DataSource(args.data_source)
    ranking = DailyRanking(fetcher=DataFetcher(data_source=source))
    ranking.load(transaction_date)

    if not ranking.items:
        print(f"{transaction_date} 无回购数据")
        return

    if args.format == "table":
        ranking.print(top_n=args.top)
    elif args.format == "json":
        print(ranking.to_json(top_n=args.top))
    elif args.format == "csv":
        print(ranking.to_csv(top_n=args.top))


def _run_single_company_summary(args: argparse.Namespace) -> None:
    from modules.analysis.single_company_daily_summary import SingleCompanyDailySummary

    date_str = args.date or date.today().isoformat()
    try:
        trade_date = date.fromisoformat(date_str)
    except ValueError:
        print(f"错误：日期格式无效 '{date_str}'，应为 YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    summary = SingleCompanyDailySummary()
    summary.load(args.ticker, trade_date)

    if not summary.data:
        print(f"{args.ticker} 在 {trade_date} 无回购数据")
        return

    md = summary.to_markdown()

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"已写入: {args.output}")
    else:
        print(md)
