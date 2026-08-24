"""single-company-daily-summary 通知动作。

查询最新未通知的回购记录，生成单公司每日回购摘要并推送到 Telegram。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from lib.db import (
    get_latest_unnotified_realtime_report,
    get_unnotified_realtime_reports_by_stock,
)
from modules.analysis.single_company_daily_summary import (
    DataFetcher,
    Renderer,
    SingleCompanyDailySummary,
)
from modules.notification.telegram import TelegramNotifier


class NotificationDataFetcher(DataFetcher):
    """仅查询未通知的回购记录，用于通知流程。"""

    @staticmethod
    def fetch(stock_code: str, trade_date: date) -> list[dict[str, Any]]:
        return get_unnotified_realtime_reports_by_stock(stock_code, trade_date.isoformat())


class SingleCompanyDailySummaryAction:
    """查询最新未通知记录 → 生成摘要 → 推送 Telegram。"""

    def __init__(
        self,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        self._notifier = notifier or TelegramNotifier()

    def execute(self) -> bool:
        """执行通知动作。返回 True 表示成功推送，False 表示无数据。"""
        record = get_latest_unnotified_realtime_report()
        if not record:
            return False

        stock_code: str = record["stock_code"]
        trade_date = date.fromisoformat(record["trade_date"])

        summary = SingleCompanyDailySummary(
            fetcher=NotificationDataFetcher(),
            renderer=Renderer(compact=True),
        )
        summary.load(stock_code, trade_date)

        if not summary.data:
            return False

        md = summary.to_markdown()
        self._notifier.send(md, markdown=True)
        return True
