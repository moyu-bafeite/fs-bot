"""港股活跃股票同步 CLI。"""

from __future__ import annotations

import argparse


def register(subparsers) -> None:
    p = subparsers.add_parser("stock-sync", help="同步 HKEX 活跃股票列表")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    from modules.stock_sync.sync import sync

    count = sync()
    print(f"完成，共写入 {count} 条股票记录")
