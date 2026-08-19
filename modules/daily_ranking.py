"""每日回购榜：查询指定交易日的港股回购数据并按金额排序展示。"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from rich.console import Console
from rich.table import Table

from lib.db import get_repurchase_actions_by_transaction_date, get_stock_names


# ── 数据模型 ──


@dataclass(frozen=True)
class RankingItem:
    """单只股票的回购排名数据。"""

    rank: int
    stock_code: str
    stock_name: dict[str, str]
    total_amount: float
    total_quantity: int
    high_price: float
    low_price: float
    action_count: int
    cumulative_quantity: int
    cumulative_percentage: float


# ── 数据获取 ──


class DataFetcher:
    """封装数据库查询逻辑。"""

    @staticmethod
    def fetch(end_date: date) -> list[dict[str, Any]]:
        """获取指定日期的回购原始数据。"""
        return get_repurchase_actions_by_transaction_date(end_date.isoformat())

    @staticmethod
    def fetch_stock_names(stock_codes: list[str]) -> dict[str, dict[str, str]]:
        """批量获取股票名称映射。"""
        return get_stock_names(stock_codes)


# ── 数据聚合 ──


class DataAggregator:
    """将原始回购记录聚合为排名数据。"""

    @staticmethod
    def aggregate(
        records: list[dict[str, Any]], stock_names: dict[str, dict[str, str]]
    ) -> list[RankingItem]:
        """按股票代码聚合回购数据，按总金额降序排序。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            code = record["stock_code"]
            grouped.setdefault(code, []).append(record)

        items: list[RankingItem] = []
        for code, actions in grouped.items():
            total_amount = sum(a["amount"] or 0 for a in actions)
            total_quantity = sum(int(a["quantity"] or 0) for a in actions)
            high_price = max((a["high_price"] or 0) for a in actions)
            low_price = min(
                (a["low_price"] for a in actions if a["low_price"] is not None),
                default=0,
            )
            cumulative_quantity = max(
                (int(a["cumulative_quantity"] or 0) for a in actions), default=0
            )
            cumulative_percentage = max(
                (a["cumulative_percentage"] or 0 for a in actions), default=0
            )

            items.append(
                RankingItem(
                    rank=0,
                    stock_code=code,
                    stock_name=stock_names.get(
                        code, {"en": "", "zh-CN": "", "zh-HK": ""}
                    ),
                    total_amount=total_amount,
                    total_quantity=total_quantity,
                    high_price=high_price,
                    low_price=low_price,
                    action_count=len(actions),
                    cumulative_quantity=cumulative_quantity,
                    cumulative_percentage=cumulative_percentage,
                )
            )

        items.sort(key=lambda x: x.total_amount, reverse=True)
        return [
            RankingItem(
                rank=i + 1,
                stock_code=item.stock_code,
                stock_name=item.stock_name,
                total_amount=item.total_amount,
                total_quantity=item.total_quantity,
                high_price=item.high_price,
                low_price=item.low_price,
                action_count=item.action_count,
                cumulative_quantity=item.cumulative_quantity,
                cumulative_percentage=item.cumulative_percentage,
            )
            for i, item in enumerate(items)
        ]


# ── 展示渲染 ──


class Renderer:
    """负责 rich 表格渲染。"""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    def render(
        self, transaction_date: date, items: list[RankingItem], top_n: int = 0
    ) -> None:
        """打印回购排行榜。"""
        display_items = items[:top_n] if top_n > 0 else items

        table = Table(
            title=f"港股回购榜 {transaction_date.isoformat()}",
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            expand=True,
        )
        table.add_column("#", justify="right", style="bold", min_width=3)
        table.add_column("代码", min_width=6)
        table.add_column("名称", min_width=10)
        table.add_column("回购金额", justify="right", min_width=14)
        table.add_column("回购数量", justify="right", min_width=10)
        # table.add_column("最高价", justify="right", min_width=8)
        # table.add_column("最低价", justify="right", min_width=8)
        # table.add_column("笔数", justify="right", min_width=4)
        table.add_column("本轮累计购回", justify="right", min_width=10)
        table.add_column("本轮累计占比", justify="right", min_width=8)

        for item in display_items:
            table.add_row(
                str(item.rank),
                item.stock_code,
                item.stock_name.get("zh-CN", ""),
                f"{item.total_amount:,.2f}",
                f"{item.total_quantity:,}",
                # f"{item.high_price:.3f}",
                # f"{item.low_price:.3f}",
                # str(item.action_count),
                f"{item.cumulative_quantity:,}",
                f"{item.cumulative_percentage:.4f}%",
            )

        self._console.print(table)
        self._console.print(
            f"\n  共 {len(items)} 只股票参与回购，"
            f"总金额 {sum(i.total_amount for i in items):,.2f}"
        )


# ── 数据导出 ──


class Exporter:
    """负责 json/csv 格式导出。"""

    @staticmethod
    def to_json(items: list[RankingItem], indent: int = 2) -> str:
        """导出为 JSON 字符串。"""
        data = [
            {
                "rank": item.rank,
                "stock_code": item.stock_code,
                "stock_name": item.stock_name,
                "total_amount": item.total_amount,
                "total_quantity": item.total_quantity,
                "high_price": item.high_price,
                "low_price": item.low_price,
                "action_count": item.action_count,
                "cumulative_quantity": item.cumulative_quantity,
                "cumulative_percentage": item.cumulative_percentage,
            }
            for item in items
        ]
        return json.dumps(data, ensure_ascii=False, indent=indent)

    @staticmethod
    def to_csv(items: list[RankingItem]) -> str:
        """导出为 CSV 字符串。"""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "rank",
                "stock_code",
                "stock_name",
                "total_amount",
                "total_quantity",
                "high_price",
                "low_price",
                "action_count",
                "cumulative_quantity",
                "cumulative_percentage",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item.rank,
                    item.stock_code,
                    item.stock_name,
                    item.total_amount,
                    item.total_quantity,
                    item.high_price,
                    item.low_price,
                    item.action_count,
                    item.cumulative_quantity,
                    item.cumulative_percentage,
                ]
            )
        return output.getvalue()


# ── 门面类 ──


class DailyRanking:
    """每日回购榜主类，协调数据获取、聚合、展示和导出。"""

    def __init__(
        self,
        fetcher: DataFetcher | None = None,
        aggregator: DataAggregator | None = None,
        renderer: Renderer | None = None,
        exporter: Exporter | None = None,
    ) -> None:
        self._fetcher = fetcher or DataFetcher()
        self._aggregator = aggregator or DataAggregator()
        self._renderer = renderer or Renderer()
        self._exporter = exporter or Exporter()
        self._items: list[RankingItem] = []
        self._transaction_date: date | None = None

    @property
    def items(self) -> list[RankingItem]:
        return self._items

    @property
    def transaction_date(self) -> date | None:
        return self._transaction_date

    def load(self, transaction_date: date) -> None:
        """加载指定交易日的回购数据并聚合。"""
        self._transaction_date = transaction_date
        records = self._fetcher.fetch(transaction_date)
        if not records:
            self._items = []
            return

        stock_codes = list({r["stock_code"] for r in records})
        stock_names = self._fetcher.fetch_stock_names(stock_codes)
        self._items = self._aggregator.aggregate(records, stock_names)

    def print(self, top_n: int = 0) -> None:
        """打印排行榜到控制台。"""
        if not self._transaction_date:
            raise RuntimeError("请先调用 load() 加载数据")
        self._renderer.render(self._transaction_date, self._items, top_n)

    def to_json(self, indent: int = 2, top_n: int = 0) -> str:
        """导出为 JSON 字符串。"""
        items = self._items[:top_n] if top_n > 0 else self._items
        return self._exporter.to_json(items, indent)

    def to_csv(self, top_n: int = 0) -> str:
        """导出为 CSV 字符串。"""
        items = self._items[:top_n] if top_n > 0 else self._items
        return self._exporter.to_csv(items)
