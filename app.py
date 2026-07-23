"""统一入口：python app.py <type> [args]"""

from __future__ import annotations

import argparse
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="HKEX 年报/中报爬虫", add_help=False)
    parser.add_argument(
        "type",
        nargs="?",
        choices=["scrape", "download", "sync-stocks", "cleanup"],
        help="任务类型",
    )
    parser.add_argument("-h", "--help", action="store_true")
    args, remaining = parser.parse_known_args()

    if args.help and args.type is None:
        parser.print_help()
        return

    if args.type is None:
        parser.print_help()
        return

    if args.type == "scrape":
        from app.scrape_meta import build_arg_parser, scrape

        sub = build_arg_parser()
        if args.help:
            sub.print_help()
            return
        opts = sub.parse_args(remaining)
        dt_from = (
            datetime.strptime(opts.date_from, "%Y-%m-%d") if opts.date_from else None
        )
        dt_to = datetime.strptime(opts.date_to, "%Y-%m-%d") if opts.date_to else None
        count = scrape(opts.tickers, dt_from, dt_to, opts.full)
        print(f"完成，共写入 {count} 条记录")

    elif args.type == "download":
        from app.download_pdf import build_arg_parser, download

        sub = build_arg_parser()
        if args.help:
            sub.print_help()
            return
        opts = sub.parse_args(remaining)
        count = download(opts.tickers, opts.limit, opts.workers)
        print(f"完成，成功下载 {count} 个 PDF")

    elif args.type == "sync-stocks":
        from app.sync_stocks import sync

        count = sync()
        print(f"完成，共写入 {count} 条股票记录")

    elif args.type == "cleanup":
        from app.cleanup_filings import build_arg_parser, cleanup

        sub = build_arg_parser()
        if args.help:
            sub.print_help()
            return
        opts = sub.parse_args(remaining)
        count = cleanup(opts.stock_code)
        print(f"完成，共删除 {count} 条噪声记录")


if __name__ == "__main__":
    main()
