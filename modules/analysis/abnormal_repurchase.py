"""回购异动：展示指定日期有回购记录的公司，按回购额占成交额占比降序排序。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from lib.db import (
    get_nr_daily_turnovers,
    get_repurchase_realtime_reports_by_trade_date,
    get_stock_names,
)


# ── 数据模型 ──


@dataclass(frozen=True)
class AbnormalItem:
    """单只股票的回购异动数据。"""

    rank: int
    stock_code: str
    stock_name: dict[str, str]
    repurchase_amount: float
    turnover: float
    ratio: float
    price_position: float
    cancellation_rate: float
    cumulative_pct: float


# ── 数据获取 ──


class DataFetcher:
    """封装数据查询逻辑。"""

    @staticmethod
    def fetch_repurchase_records(trade_date: date) -> list[dict[str, Any]]:
        return get_repurchase_realtime_reports_by_trade_date(trade_date.isoformat())

    @staticmethod
    def fetch_turnovers(trade_date: date) -> dict[str, float]:
        return get_nr_daily_turnovers(trade_date.isoformat())

    @staticmethod
    def fetch_stock_names(stock_codes: list[str]) -> dict[str, dict[str, str]]:
        return get_stock_names(stock_codes)


# ── 数据聚合 ──


class DataAggregator:
    """将原始记录聚合为 AbnormalItem 列表。"""

    @staticmethod
    def aggregate(
        records: list[dict[str, Any]],
        turnovers: dict[str, float],
        stock_names: dict[str, dict[str, str]],
        threshold: float,
    ) -> list[AbnormalItem]:
        """按 stock_code 聚合，计算各项指标，过滤阈值，按 ratio 降序排序。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for rec in records:
            grouped.setdefault(rec["stock_code"], []).append(rec)

        items: list[AbnormalItem] = []
        for code, rows in grouped.items():
            turnover = turnovers.get(code)
            if not turnover or turnover <= 0:
                continue

            hkd_rows = [r for r in rows if r.get("currency") == "HKD"]
            if not hkd_rows:
                continue

            amount = sum(float(r["amount"] or 0) for r in hkd_rows)
            quantity = sum(int(r["quantity"] or 0) for r in hkd_rows)
            ratio = amount / turnover

            if ratio * 100 < threshold:
                continue

            # 价格位置：(均价 - 最低) / (最高 - 最低)
            high_price = max(float(r["high_price"] or 0) for r in hkd_rows)
            low_price = min(
                (float(r["low_price"]) for r in hkd_rows if r.get("low_price") is not None),
                default=0.0,
            )
            avg_price = amount / quantity if quantity > 0 else 0.0
            if high_price > low_price > 0:
                price_position = (avg_price - low_price) / (high_price - low_price)
            else:
                price_position = 0.0

            # 注销率
            for_cancellation = sum(int(r["for_cancellation"] or 0) for r in hkd_rows)
            cancellation_rate = for_cancellation / quantity if quantity > 0 else 0.0

            # 本轮累计占比
            cumulative_pct = max(
                (float(r["cumulative_pct"] or 0) for r in rows), default=0.0
            )

            items.append(
                AbnormalItem(
                    rank=0,
                    stock_code=code,
                    stock_name=stock_names.get(code, {"en": "", "zh-CN": "", "zh-HK": ""}),
                    repurchase_amount=amount,
                    turnover=turnover,
                    ratio=ratio,
                    price_position=price_position,
                    cancellation_rate=cancellation_rate,
                    cumulative_pct=cumulative_pct,
                )
            )

        items.sort(key=lambda x: x.ratio, reverse=True)
        return [
            AbnormalItem(
                rank=i + 1,
                stock_code=item.stock_code,
                stock_name=item.stock_name,
                repurchase_amount=item.repurchase_amount,
                turnover=item.turnover,
                ratio=item.ratio,
                price_position=item.price_position,
                cancellation_rate=item.cancellation_rate,
                cumulative_pct=item.cumulative_pct,
            )
            for i, item in enumerate(items)
        ]


# ── Markdown 渲染 ──


def _format_amount(value: float) -> str:
    """将金额格式化为 B/M/K 简写。"""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.2f}K"
    return f"{value:,.2f}"


class Renderer:
    """将 AbnormalItem 列表渲染为 Markdown。"""

    def __init__(self, *, compact: bool = False) -> None:
        self._compact = compact

    def render(
        self, trade_date: date, items: list[AbnormalItem], limit: int
    ) -> str:
        if self._compact:
            return self._render_message(trade_date, items, limit)
        return self._render_markdown(trade_date, items, limit)

    def _render_markdown(
        self, trade_date: date, items: list[AbnormalItem], limit: int
    ) -> str:
        display_items = items[:limit] if limit > 0 else items
        if not display_items:
            return ""

        lines: list[str] = []
        lines.append(f"# 回购异动 ({trade_date.isoformat()})")
        lines.append("")
        lines.append("| # | 股票 | 回购额 | 成交额 | 占比 | 价格位置 | 注销率 | 累计进度 |")
        lines.append("|---|---|---|---|---|---|---|---|")

        for item in display_items:
            name = item.stock_name.get("zh-CN") or item.stock_name.get("en") or ""
            lines.append(
                f"| {item.rank} "
                f"| {item.stock_code} {name} "
                f"| {_format_amount(item.repurchase_amount)} "
                f"| {_format_amount(item.turnover)} "
                f"| {item.ratio:.2%} "
                f"| {item.price_position:.2f} "
                f"| {item.cancellation_rate:.0%} "
                f"| {item.cumulative_pct:.4f}% |"
            )

        lines.append("")
        return "\n".join(lines)

    def _render_message(
        self, trade_date: date, items: list[AbnormalItem], limit: int
    ) -> str:
        display_items = items[:limit] if limit > 0 else items
        if not display_items:
            return ""

        lines: list[str] = []
        lines.append(f"#回购异动 {trade_date.isoformat()}")
        lines.append("")

        for item in display_items:
            name = item.stock_name.get("zh-CN") or item.stock_name.get("en") or ""
            lines.append(f"{item.rank}. `{item.stock_code} {name}`")
            lines.append(
                f"回购 {_format_amount(item.repurchase_amount)} "
                f"/ 成交 {_format_amount(item.turnover)} · 占比 {item.ratio:.2%}"
            )
            lines.append(
                f"价格位置 {item.price_position:.2f} "
                f"· 注销率 {item.cancellation_rate:.0%} "
                f"· 累计 {item.cumulative_pct:.2f}%"
            )
            lines.append("")

        lines.append("— — —")
        lines.append("价格位置：回购均价在当日价格区间中的位置（0=最低，1=最高）")
        lines.append("注销率：用于注销的回购数量占当日总回购数量的比例")
        lines.append("累计：本轮授权以来的累计回购占比")

        return "\n".join(lines)


# ── 门面类 ──


class AbnormalRepurchase:
    """回购异动主类，协调数据获取、聚合和渲染。"""

    def __init__(
        self,
        fetcher: DataFetcher | None = None,
        aggregator: DataAggregator | None = None,
        renderer: Renderer | None = None,
    ) -> None:
        self._fetcher = fetcher or DataFetcher()
        self._aggregator = aggregator or DataAggregator()
        self._renderer = renderer or Renderer()
        self._items: list[AbnormalItem] = []
        self._trade_date: date | None = None

    @property
    def items(self) -> list[AbnormalItem]:
        return self._items

    def load(self, trade_date: date, threshold: float = 10.0) -> None:
        """加载指定交易日数据并聚合。"""
        self._trade_date = trade_date
        records = self._fetcher.fetch_repurchase_records(trade_date)
        if not records:
            self._items = []
            return

        turnovers = self._fetcher.fetch_turnovers(trade_date)
        stock_codes = list({r["stock_code"] for r in records})
        stock_names = self._fetcher.fetch_stock_names(stock_codes)
        self._items = self._aggregator.aggregate(records, turnovers, stock_names, threshold)

    def to_markdown(self, limit: int = 10) -> str:
        """导出为 Markdown 字符串。"""
        if not self._trade_date:
            return ""
        return self._renderer.render(self._trade_date, self._items, limit)
