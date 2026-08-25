"""single-company-daily-summary 通知动作。

查询最新未通知的回购记录，生成单公司每日回购摘要并推送到 Telegram。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from rich.console import Console

from lib.db import (
    get_latest_unnotified_realtime_report,
    get_unnotified_realtime_reports_by_stock,
    mark_realtime_reports_notified,
)
from modules.analysis.single_company_daily_summary import (
    DataFetcher,
    Renderer,
    SingleCompanyDailySummary,
)
from modules.notification.telegram import TelegramNotifier


class NotificationDataFetcher(DataFetcher):
    """返回预取的记录列表，用于通知流程。"""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def repurchase_reports(self, stock_code: str, trade_date: date) -> list[dict[str, Any]]:
        return self._records


class SingleCompanyDailySummaryAction:
    """查询最新未通知记录 → 生成摘要 → 推送 Telegram。"""

    def __init__(
        self,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        self._notifier = notifier or TelegramNotifier()

    def execute(self) -> dict[str, Any] | None:
        """执行通知动作。返回触发的记录，无数据时返回 None。"""
        latest_record = get_latest_unnotified_realtime_report()
        if not latest_record:
            return None

        stock_code: str = latest_record["stock_code"]
        trade_date = date.fromisoformat(latest_record["trade_date"])

        records = get_unnotified_realtime_reports_by_stock(stock_code, trade_date.isoformat())
        if not records:
            return None

        ids = [r["id"] for r in records]

        # 检测是否有 trade_date 的股价数据，无则返回 None
        fetcher = NotificationDataFetcher(records)
        if (fetcher.turnover(stock_code, trade_date) == None):
            Console().print(f"[yellow]WARNING: {stock_code} 在 {trade_date} 无最新股价数据[/yellow]")
            return None

        summary = SingleCompanyDailySummary(
            fetcher=fetcher,
            renderer=Renderer(compact=True),
        )
        summary.load(stock_code, trade_date)

        if not summary.data:
            return None

        md = summary.to_markdown()
        self._notifier.send(md, markdown=True)
        mark_realtime_reports_notified(ids)
        return latest_record
