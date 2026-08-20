"""统一入口：python app.py <type> [args]"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description="港股股票同步工具", add_help=False)
    parser.add_argument(
        "type",
        nargs="?",
        choices=[
            "sync-hk-stocks",
            "fetch-hk-repurchase-actions",
            "push-hk-repurchase-actions",
            "generate-daily-ranking",
            "fetch-stocks-of-multiple-exchanges",
            "download-hkex-srrpt",
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

    elif args.type == "generate-daily-ranking":
        import sys

        from app.generate_daily_ranking import main as generate_ranking_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["generate-daily-ranking", "--help"]
            else:
                sys.argv = ["generate-daily-ranking"] + remaining
            generate_ranking_main()
        finally:
            sys.argv = old_argv

    elif args.type == "fetch-stocks-of-multiple-exchanges":
        import sys

        from app.fetch_stocks_of_multiple_exchanges import main as fetch_stocks_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["fetch-stocks-of-multiple-exchanges", "--help"]
            else:
                sys.argv = ["fetch-stocks-of-multiple-exchanges"] + remaining
            fetch_stocks_main()
        finally:
            sys.argv = old_argv

    elif args.type == "download-hkex-srrpt":
        import sys

        from app.download_hkex_srrpt import main as download_srrpt_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["download-hkex-srrpt", "--help"]
            else:
                sys.argv = ["download-hkex-srrpt"] + remaining
            download_srrpt_main()
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    main()
