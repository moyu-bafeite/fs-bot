"""通知模块 CLI。

子命令:
  send - 读取 Markdown 文件并推送到 Telegram
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register(subparsers) -> None:
    p = subparsers.add_parser("notification", help="消息推送")
    sub = p.add_subparsers(dest="notification_command")

    sd = sub.add_parser("send", help="推送 Markdown 文件到 Telegram")
    sd.add_argument("--file", required=True, type=str, help="Markdown 文件路径")

    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    cmd = getattr(args, "notification_command", None)
    if cmd == "send":
        _run_send(args)
    else:
        from rich.console import Console

        Console().print("[yellow]请指定子命令: send --file <path>[/yellow]")
        sys.exit(1)


def _run_send(args: argparse.Namespace) -> None:
    from rich.console import Console
    from modules.notification.telegram import TelegramNotifier

    path = Path(args.file)
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
