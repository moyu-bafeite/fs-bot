"""数据分析处理器 CLI。

子命令:
  daily-ranking - 生成每日回购排行榜
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
    dr.add_argument("--output", type=str, default=None, help="输出文件路径")
    dr.add_argument("--local", action="store_true", help="从本地 output/srann/ 读取数据")

    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    cmd = getattr(args, "analysis_command", None)
    if cmd == "daily-ranking":
        _run_daily_ranking(args)
    else:
        sys.argv = ["analysis", "--help"]
        p = argparse.ArgumentParser(description="数据分析")
        sub = p.add_subparsers(dest="cmd")
        sub.add_parser("daily-ranking")
        p.parse_args(["--help"])


def _run_daily_ranking(args: argparse.Namespace) -> None:
    from modules.analysis.daily_ranking import DailyRanking, DataFetcherLocal

    try:
        transaction_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"错误：日期格式无效 '{args.date}'，应为 YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    fetcher = DataFetcherLocal() if args.local else None
    ranking = DailyRanking(fetcher=fetcher)
    ranking.load(transaction_date)

    if not ranking.items:
        print(f"{transaction_date} 无回购数据")
        return

    if args.format == "table":
        ranking.print(top_n=args.top)
    elif args.format == "json":
        output = ranking.to_json(top_n=args.top)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"已写入: {args.output}")
        else:
            print(output)
    elif args.format == "csv":
        output = ranking.to_csv(top_n=args.top)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"已写入: {args.output}")
        else:
            print(output)
