"""每日回购榜：查询指定交易日的港股回购数据并按金额排序展示。"""

from __future__ import annotations

import enum
import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from lib.db import (
    get_repurchase_reports_by_trade_date,
    get_repurchase_realtime_reports_by_trade_date,
    get_stock_names,
)

_LOCAL_DATA_DIR = Path("output/srann")


# ── 数据模型 ──


class DataSource(enum.Enum):
    """数据来源枚举。"""

    LOCAL = "local"
    HKEX_REPORTS = "hkex_repurchase_reports"
    HKEX_REALTIME = "hkex_repurchase_realtime_reports"


@dataclass(frozen=True)
class RankingItem:
    """单只股票的回购排名数据。"""

    rank: int
    stock_code: str
    stock_name: dict[str, str]
    currency: str
    total_amount: float
    total_quantity: int
    high_price: float
    low_price: float
    action_count: int
    cumulative_quantity: int
    cumulative_pct: float
    for_cancellation: int
    for_treasury: int


# ── 数据获取 ──


class DataFetcher:
    """封装数据查询逻辑，根据 data_source 选择数据来源。"""

    def __init__(self, data_source: DataSource = DataSource.HKEX_REPORTS) -> None:
        self._data_source = data_source

    def fetch(self, trade_date: date) -> list[dict[str, Any]]:
        """获取指定交易日的回购数据。"""
        if self._data_source == DataSource.HKEX_REPORTS:
            return get_repurchase_reports_by_trade_date(trade_date.isoformat())
        if self._data_source == DataSource.HKEX_REALTIME:
            return get_repurchase_realtime_reports_by_trade_date(trade_date.isoformat())
        return self._fetch_local(trade_date)

    @staticmethod
    def fetch_stock_names(stock_codes: list[str]) -> dict[str, dict[str, str]]:
        """批量获取股票名称映射。"""
        return get_stock_names(stock_codes)

    @staticmethod
    def _fetch_local(trade_date: date) -> list[dict[str, Any]]:
        """从本地 output/srann/ 目录读取 LLM 解析的回购数据。"""
        if not _LOCAL_DATA_DIR.exists():
            return []

        files = list(_LOCAL_DATA_DIR.glob("*.json"))
        if not files:
            return []

        date_str = trade_date.isoformat()
        records: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=100) as pool:
            futures = {pool.submit(DataFetcher._load_json_file, f): f for f in files}
            for future in as_completed(futures):
                try:
                    rows = future.result()
                    for row in rows:
                        if row.get("trade_date") == date_str:
                            records.append(row)
                except (json.JSONDecodeError, OSError):
                    continue

        return records

    @staticmethod
    def _load_json_file(path: Path) -> list[dict[str, Any]]:
        """读取单个 JSON 文件，返回记录列表。"""
        with open(path, encoding="utf-8") as f:
            return json.load(f)


# ── 数据聚合 ──


class DataAggregator:
    """将原始回购记录聚合为排名数据。"""

    @staticmethod
    def aggregate(
        records: list[dict[str, Any]], stock_names: dict[str, dict[str, str]]
    ) -> list[RankingItem]:
        """按股票代码+币种聚合回购数据，按总金额降序排序。"""
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for record in records:
            code = record["stock_code"]
            currency = record.get("currency", "")
            grouped.setdefault((code, currency), []).append(record)

        items: list[RankingItem] = []
        for (code, currency), actions in grouped.items():
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
            cumulative_pct = max((a["cumulative_pct"] or 0 for a in actions), default=0)
            for_cancellation = sum(int(a["for_cancellation"] or 0) for a in actions)
            for_treasury = sum(int(a["for_treasury"] or 0) for a in actions)

            items.append(
                RankingItem(
                    rank=0,
                    stock_code=code,
                    stock_name=stock_names.get(
                        code, {"en": "", "zh-CN": "", "zh-HK": ""}
                    ),
                    currency=currency,
                    total_amount=total_amount,
                    total_quantity=total_quantity,
                    high_price=high_price,
                    low_price=low_price,
                    action_count=len(actions),
                    cumulative_quantity=cumulative_quantity,
                    cumulative_pct=cumulative_pct,
                    for_cancellation=for_cancellation,
                    for_treasury=for_treasury,
                )
            )

        items.sort(key=lambda x: x.total_amount, reverse=True)
        return [
            RankingItem(
                rank=i + 1,
                stock_code=item.stock_code,
                stock_name=item.stock_name,
                currency=item.currency,
                total_amount=item.total_amount,
                total_quantity=item.total_quantity,
                high_price=item.high_price,
                low_price=item.low_price,
                action_count=item.action_count,
                cumulative_quantity=item.cumulative_quantity,
                cumulative_pct=item.cumulative_pct,
                for_cancellation=item.for_cancellation,
                for_treasury=item.for_treasury,
            )
            for i, item in enumerate(items)
        ]


# ── 展示渲染 ──


class TerminalRenderer:
    """负责 rich 终端表格渲染，返回 ANSI 文本。"""

    def render(
        self, trade_date: date, items: list[RankingItem], top_n: int = 0
    ) -> str:
        """渲染回购排行榜，返回 ANSI 文本。"""
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True)
        display_items = items[:top_n] if top_n > 0 else items

        # 按币种分组
        currencies = list(dict.fromkeys(item.currency for item in display_items))

        for currency in currencies:
            group = [item for item in display_items if item.currency == currency]
            if not group:
                continue

            table = Table(
                title=f"港股回购榜 {trade_date.isoformat()} ({currency})",
                show_header=True,
                header_style="bold cyan",
                border_style="dim",
                expand=True,
            )
            table.add_column("#", justify="right", style="bold", min_width=3)
            table.add_column("股票", min_width=16)
            table.add_column("回购金额", justify="right", min_width=14)
            table.add_column("回购数量", justify="right", min_width=16)
            table.add_column("本轮累计回购", justify="right", min_width=10)
            table.add_column("本轮累计占比", justify="right", min_width=8)

            for rank, item in enumerate(group, 1):
                stock_display = f"{item.stock_code} {item.stock_name.get('zh-CN', '')}"

                qty_parts = [f"{item.total_quantity:,}"]
                if item.for_cancellation > 0:
                    qty_parts.append("[green](C)[/green]")
                if item.for_treasury > 0:
                    qty_parts.append("(T)")
                qty_display = " ".join(qty_parts)

                table.add_row(
                    str(rank),
                    stock_display,
                    f"{item.total_amount:,.2f}",
                    qty_display,
                    f"{item.cumulative_quantity:,}"
                    if item.cumulative_quantity > 0
                    else "—",
                    f"{item.cumulative_pct:.4f}%" if item.cumulative_pct > 0 else "—",
                )

            console.print(table)
            console.print()

        unique_companies = len({item.stock_code for item in items})
        console.print(f"共 {unique_companies} 家公司进行回购")
        console.print()
        console.print(
            "[dim]* 「本轮累计回购」指最新的股东大会决议案通过后的回购累计数量[/dim]"
        )
        console.print(
            "[dim]* 「本轮累计占比」指累计回购股份数占最新的股东大会决议案通过当日的已发行股份（不包含库存股）的百分比[/dim]"
        )

        return buf.getvalue()


# ── 门面类 ──


class DailyRanking:
    """每日回购榜主类，协调数据获取、聚合和展示。"""

    def __init__(
        self,
        fetcher: DataFetcher | None = None,
        aggregator: DataAggregator | None = None,
        renderer: TerminalRenderer | None = None,
    ) -> None:
        self._fetcher = fetcher or DataFetcher()
        self._aggregator = aggregator or DataAggregator()
        self._renderer = renderer
        self._items: list[RankingItem] = []
        self._trade_date: date | None = None

    @property
    def items(self) -> list[RankingItem]:
        return self._items

    @property
    def trade_date(self) -> date | None:
        return self._trade_date

    def load(self, trade_date: date) -> None:
        """加载指定交易日的回购数据并聚合。"""
        self._trade_date = trade_date
        records = self._fetcher.fetch(trade_date)
        if not records:
            self._items = []
            return

        stock_codes = list({r["stock_code"] for r in records})
        stock_names = self._fetcher.fetch_stock_names(stock_codes)
        self._items = self._aggregator.aggregate(records, stock_names)

    def print(self, top_n: int = 0) -> None:
        """打印排行榜到控制台。"""
        if not self._trade_date:
            raise RuntimeError("请先调用 load() 加载数据")
        if not self._renderer:
            raise RuntimeError("未配置渲染器，请传入 TerminalRenderer")
        print(self._renderer.render(self._trade_date, self._items, top_n))
