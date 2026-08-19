"""统一入口：python app.py <type> [args]"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="港股/美股股票同步工具", add_help=False
    )
    parser.add_argument(
        "type",
        nargs="?",
        choices=[
            "sync-hk-stocks",
            "sync-us-stocks",
            "sync-us-sec-cik-mappings",
            "fetch-us-fs",
            "push-us-fs",
            "show-fs",
            "fetch-us-form4-index",
            "parse-us-form4",
            "push-us-form4",
            "build-form4-defs",
            "fetch-hk-repurchase-actions",
            "push-hk-repurchase-actions",
        ],
        help="任务类型",
    )
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="环境（dev=.env.dev, prod=.env.prod）",
    )
    args, remaining = parser.parse_known_args()
    load_dotenv(f".env.{args.env}")

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
        count = sync(full=opts.full, workers=opts.workers, interval=opts.interval)
        print(f"完成，共写入 {count} 条美股记录")

    elif args.type == "sync-us-sec-cik-mappings":
        from app.sync_us_sec_cik_mappings import sync

        count = sync()
        print(f"完成，共写入 {count} 条 CIK 映射记录")

    elif args.type == "fetch-us-fs":
        import sys

        from app.fetch_us_fs import main as fetch_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["fetch-us-fs", "--help"]
            else:
                sys.argv = ["fetch-us-fs"] + remaining
            fetch_main()
        finally:
            sys.argv = old_argv

    elif args.type == "push-us-fs":
        import sys

        from app.push_us_fs import main as push_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["push-us-fs", "--help"]
            else:
                sys.argv = ["push-us-fs"] + remaining
            push_main()
        finally:
            sys.argv = old_argv

    elif args.type == "show-fs":
        from app.show_fs import main as show_main

        show_main(remaining)

    elif args.type == "fetch-us-form4-index":
        import sys

        from app.fetch_us_form4_index import main as fetch_index_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["fetch-us-form4-index", "--help"]
            else:
                sys.argv = ["fetch-us-form4-index"] + remaining
            fetch_index_main()
        finally:
            sys.argv = old_argv

    elif args.type == "parse-us-form4":
        import sys

        from app.parse_us_form4 import main as parse_form4_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["parse-us-form4", "--help"]
            else:
                sys.argv = ["parse-us-form4"] + remaining
            parse_form4_main()
        finally:
            sys.argv = old_argv

    elif args.type == "push-us-form4":
        import sys

        from app.push_us_form4 import main as push_form4_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["push-us-form4", "--help"]
            else:
                sys.argv = ["push-us-form4"] + remaining
            push_form4_main()
        finally:
            sys.argv = old_argv

    elif args.type == "build-form4-defs":
        import sys

        from app.build_form4_defs import main as build_defs_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["build-form4-defs", "--help"]
            else:
                sys.argv = ["build-form4-defs"] + remaining
            build_defs_main()
        finally:
            sys.argv = old_argv

    elif args.type == "fetch-hk-repurchase-actions":
        import sys

        from app.fetch_hk_repurchase_actions import main as fetch_repurchase_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["fetch-hk-repurchase-actions", "--help"]
            else:
                sys.argv = ["fetch-hk-repurchase-actions"] + remaining
            fetch_repurchase_main()
        finally:
            sys.argv = old_argv

    elif args.type == "push-hk-repurchase-actions":
        import sys

        from app.push_hk_repurchase_actions import main as push_repurchase_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["push-hk-repurchase-actions", "--help"]
            else:
                sys.argv = ["push-hk-repurchase-actions"] + remaining
            push_repurchase_main()
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    main()
