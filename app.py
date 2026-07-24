"""统一入口：python app.py <type> [args]"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="港股/美股股票同步工具", add_help=False
    )
    parser.add_argument(
        "type",
        nargs="?",
        choices=["sync-hk-stocks", "sync-us-stocks", "sync-us-fs"],
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

    if args.type == "sync-hk-stocks":
        from app.sync_hk_stocks import sync

        count = sync()
        print(f"完成，共写入 {count} 条股票记录")

    elif args.type == "sync-us-stocks":
        from app.sync_us_stocks import build_arg_parser, sync

        sub = build_arg_parser()
        if args.help:
            sub.print_help()
            return
        opts = sub.parse_args(remaining)
        count = sync(opts.full)
        print(f"完成，共写入 {count} 条美股记录")

    elif args.type == "sync-us-fs":
        import sys

        from app.sync_us_stocks_fs import main as fs_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["sync-us-fs", "--help"]
            else:
                sys.argv = ["sync-us-fs"] + remaining
            fs_main()
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    main()
