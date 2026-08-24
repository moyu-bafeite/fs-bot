"""通知模块 CLI。

子命令:
  send - 推送消息到 Telegram
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ACTIONS = ["single-company-daily-summary"]


def register(subparsers) -> None:
    p = subparsers.add_parser("notification", help="消息推送")
    sub = p.add_subparsers(dest="notification_command")

    sd = sub.add_parser("send", help="推送消息到 Telegram")
    sd.add_argument("--file", type=str, default=None, help="Markdown 文件路径")
    sd.add_argument(
        "--action",
        type=str,
        choices=_ACTIONS,
        default=None,
        help="预定义动作",
    )

    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    cmd = getattr(args, "notification_command", None)
    if cmd == "send":
        _run_send(args)
    else:
        from rich.console import Console

        Console().print("[yellow]请指定子命令: send --file <path> | send --action <name>[/yellow]")
        sys.exit(1)


def _run_send(args: argparse.Namespace) -> None:
    from rich.console import Console

    if args.action and args.file:
        Console().print("[red]--file 和 --action 不能同时使用[/red]")
        sys.exit(1)

    if not args.action and not args.file:
        Console().print("[red]请指定 --file 或 --action[/red]")
        sys.exit(1)

    if args.action:
        _run_action(args.action)
    else:
        _run_file(args.file)


def _run_file(file_path: str) -> None:
    from rich.console import Console
    from modules.notification.telegram import TelegramNotifier

    path = Path(file_path)
    if not path.exists():
        Console().print(f"[red]文件不存在: {path}[/red]")
        sys.exit(1)

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        Console().print("[yellow]文件内容为空[/yellow]")
        return

    notifier = TelegramNotifier()
    notifier.send(text, markdown=True)
    Console().print(f"[green]✓[/green] 已推送 {path.name}")


def _run_action(action_name: str) -> None:
    from rich.console import Console

    if action_name == "single-company-daily-summary":
        from modules.notification.actions.single_company_daily_summary import (
            SingleCompanyDailySummaryAction,
        )

        action = SingleCompanyDailySummaryAction()
        record = action.execute()
        if record:
            Console().print(f"[green]✓[/green] 已推送 {record['stock_code']} {record['trade_date']}")
            Console().print(record)
        else:
            Console().print("[yellow]无未通知的回购数据[/yellow]")
