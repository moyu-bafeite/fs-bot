#!/usr/bin/env python3
"""生成每日回购排行榜。"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from modules.daily_ranking import DailyRanking


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="生成每日回购排行榜")
    p.add_argument(
        "--date",
        type=str,
        required=True,
        help="交易日期 (YYYY-MM-DD)",
    )
    p.add_argument(
        "--top",
        type=int,
        default=0,
        help="只显示前 N 名 (0=全部)",
    )
    p.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="输出格式 (默认 table)",
    )
    p.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件路径 (默认 stdout)",
    )
    return p.parse_args()


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()

    try:
        transaction_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"错误：日期格式无效 '{args.date}'，应为 YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    ranking = DailyRanking()
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


if __name__ == "__main__":
    main()
