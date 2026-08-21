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
            "sync-hk-stocks-handler",
            "daily-ranking",
            "hkex-srrpt-downloader",
            "hkex-srrpt-parser",
            "hkex-srrpt-uploader",
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

    if args.type == "hk-stocks-handler":
        from app.sync_hk_stocks import sync

        count = sync()
        print(f"完成，共写入 {count} 条股票记录")

    elif args.type == "daily-ranking":
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

    elif args.type == "hkex-srrpt-downloader":
        import sys

        from app.hkex_srrpt_downloader import main as download_srrpt_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["hkex-srrpt-downloader", "--help"]
            else:
                sys.argv = ["hkex-srrpt-downloader"] + remaining
            download_srrpt_main()
        finally:
            sys.argv = old_argv

    elif args.type == "hkex-srrpt-parser":
        import sys

        from app.hkex_srrpt_parser import main as parse_srrpt_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["hkex-srrpt-parser", "--help"]
            else:
                sys.argv = ["hkex-srrpt-parser"] + remaining
            parse_srrpt_main()
        finally:
            sys.argv = old_argv

    elif args.type == "hkex-srrpt-uploader":
        import sys

        from app.hkex_srrpt_uploader import main as upload_srrpt_main

        old_argv = sys.argv
        try:
            if args.help:
                sys.argv = ["hkex-srrpt-uploader", "--help"]
            else:
                sys.argv = ["hkex-srrpt-uploader"] + remaining
            upload_srrpt_main()
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    main()
