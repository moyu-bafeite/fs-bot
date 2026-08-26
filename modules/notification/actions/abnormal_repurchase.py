"""abnormal-repurchase 通知动作。

查询当日回购异动数据并推送到 Telegram。
"""

from __future__ import annotations

from datetime import date, datetime

from modules.analysis.abnormal_repurchase import (
    AbnormalRepurchase,
    Renderer,
)
from modules.notification.telegram import TelegramNotifier


class AbnormalRepurchaseAction:
    """查询当日回购异动 → 生成摘要 → 推送 Telegram。"""

    def __init__(
        self,
        notifier: TelegramNotifier | None = None,
        threshold: float = 10.0,
        limit: int = 10,
    ) -> None:
        self._notifier = notifier or TelegramNotifier()
        self._threshold = threshold
        self._limit = limit

    def execute(self, trade_date: date | None = None) -> bool:
        """执行通知动作。返回 True 表示成功推送，False 表示无数据。"""
        trade_date = trade_date or datetime.now().date()

        ar = AbnormalRepurchase(renderer=Renderer(compact=True))
        ar.load(trade_date, threshold=self._threshold)

        if not ar.items:
            return False

        md = ar.to_markdown(limit=self._limit)
        if not md:
            return False

        self._notifier.send(md, markdown=True)
        return True
