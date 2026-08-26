"""通知模块 CLI。

子命令:
  send - 推送消息到 Telegram
"""

from __future__ import annotations

from datetime import datetime
import sys
from pathlib import Path
from typing import Annotated, Literal

import typer

_ACTIONS = ["single-company-daily-summary", "abnormal-repurchase"]

app = typer.Typer(help="消息推送")


@app.command()
def send(
    file: Annotated[str, typer.Option(help="Markdown 文件路径")] = "",
    action: Annotated[str, typer.Option(help="预定义动作")] = "",
):
    """推送消息到 Telegram。"""
    from rich.console import Console

    console = Console()

    if action and file:
        console.print("[red]--file 和 --action 不能同时使用[/red]")
        raise typer.Exit(code=1)

    if not action and not file:
        console.print("[red]请指定 --file 或 --action[/red]")
        raise typer.Exit(code=1)

    if action:
        _run_action(action, console)
    else:
        _run_file(file, console)


def _run_file(file_path: str, console) -> None:
    from modules.notification.telegram import TelegramNotifier

    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]文件不存在: {path}[/red]")
        raise typer.Exit(code=1)

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        console.print("[yellow]文件内容为空[/yellow]")
        return

    notifier = TelegramNotifier()
    notifier.send(text, markdown=True)
    console.print(f"[green]✓[/green] 已推送 {path.name}")


def _run_action(action_name: str, console) -> None:
    if action_name == "single-company-daily-summary":
        from modules.notification.actions.single_company_daily_summary import (
            SingleCompanyDailySummaryAction,
        )

        action = SingleCompanyDailySummaryAction()
        record = action.execute()
        if record:
            console.print(f"[green]✓[/green] 已推送 {record['stock_code']} {record['trade_date']}")
            console.print(record)
        else:
            console.print("[yellow]WARNING: 无未通知的回购数据[/yellow]")
    elif action_name == "abnormal-repurchase":
        from modules.notification.actions.abnormal_repurchase import (
            AbnormalRepurchaseAction,
        )

        action = AbnormalRepurchaseAction()
        pushed = action.execute()
        if pushed:
            console.print(f"[green]✓[/green] 已推送 {datetime.now().date()} 回购异动")
        else:
            console.print(f"[yellow]WARNING: {datetime.now().date()} 无回购异动数据[/yellow]")
    else:
        console.print(f"[red]未知动作: {action_name}[/red]")
        console.print(f"可用动作: {', '.join(_ACTIONS)}")
        raise typer.Exit(code=1)
