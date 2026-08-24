"""单公司每日回购摘要：展示指定股票在指定交易日的回购情况与分析，输出 Markdown。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from lib.db import get_realtime_reports_by_stock, get_unnotified_realtime_reports_by_stock, get_stock_names


# ── 数据模型 ──


@dataclass(frozen=True)
class CurrencySummary:
    """单一币种的回购汇总。"""

    currency: str
    total_quantity: int
    total_amount: float
    high_price: float
    low_price: float
    avg_price: float
    for_cancellation: int
    for_treasury: int
    action_count: int


@dataclass(frozen=True)
class CompanyDailyData:
    """单只股票单日的回购全貌。"""

    stock_code: str
    stock_name: dict[str, str]
    trade_date: date
    by_currency: list[CurrencySummary]
    cumulative_quantity: int
    cumulative_pct: float
    document_urls: list[str]


# ── 数据获取 ──


class DataFetcher:
    """封装数据库查询逻辑。"""

    @staticmethod
    def fetch(stock_code: str, trade_date: date) -> list[dict[str, Any]]:
        return get_realtime_reports_by_stock(stock_code, trade_date.isoformat())

    @staticmethod
    def fetch_unnotified(stock_code: str, trade_date: date) -> list[dict[str, Any]]:
        return get_unnotified_realtime_reports_by_stock(stock_code, trade_date.isoformat())

    @staticmethod
    def fetch_stock_name(stock_code: str) -> dict[str, str]:
        names = get_stock_names([stock_code])
        return names.get(stock_code, {"en": "", "zh-CN": "", "zh-HK": ""})


# ── 数据聚合 ──


class DataAggregator:
    """将原始记录按币种聚合为 CurrencySummary 列表。"""

    @staticmethod
    def aggregate(records: list[dict[str, Any]]) -> tuple[list[CurrencySummary], int, float, list[str]]:
        """返回 (按币种汇总列表, 累计回购数量, 累计占比, 参考链接列表)。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for rec in records:
            grouped.setdefault(rec.get("currency", ""), []).append(rec)

        summaries: list[CurrencySummary] = []
        for currency, rows in sorted(grouped.items()):
            total_amount = sum(float(r["amount"] or 0) for r in rows)
            total_quantity = sum(int(r["quantity"] or 0) for r in rows)
            high_price = max(float(r["high_price"] or 0) for r in rows)
            low_price = min(
                (float(r["low_price"]) for r in rows if r.get("low_price") is not None),
                default=0.0,
            )
            avg_price = total_amount / total_quantity if total_quantity > 0 else 0.0
            for_cancellation = sum(int(r["for_cancellation"] or 0) for r in rows)
            for_treasury = sum(int(r["for_treasury"] or 0) for r in rows)

            summaries.append(
                CurrencySummary(
                    currency=currency,
                    total_quantity=total_quantity,
                    total_amount=total_amount,
                    high_price=high_price,
                    low_price=low_price,
                    avg_price=avg_price,
                    for_cancellation=for_cancellation,
                    for_treasury=for_treasury,
                    action_count=len(rows),
                )
            )

        cumulative_quantity = max(
            (int(r["cumulative_quantity"] or 0) for r in records), default=0
        )
        cumulative_pct = max(
            (float(r["cumulative_pct"] or 0) for r in records), default=0.0
        )

        document_urls = list(dict.fromkeys(
            r["document_url"] for r in records if r.get("document_url")
        ))

        return summaries, cumulative_quantity, cumulative_pct, document_urls


# ── Markdown 渲染 ──


class Renderer:
    """将 CompanyDailyData 渲染为 Markdown 字符串。"""

    def render(self, data: CompanyDailyData) -> str:
        lines: list[str] = []
        name_display = data.stock_name.get("zh-CN") or data.stock_name.get("en") or ""
        title = f"{data.stock_code} {name_display}".strip()

        lines.append(f"# {title} — {data.trade_date.isoformat()} 回购摘要")
        lines.append("")

        # 概览
        lines.append("## 概览")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        if data.cumulative_quantity > 0:
            lines.append(f"| 本轮累计回购 | {data.cumulative_quantity:,} 股 |")
        if data.cumulative_pct > 0:
            lines.append(f"| 本轮累计占比 | {data.cumulative_pct:.4f}% |")
        lines.append("")

        # 分币种明细
        lines.append("## 分币种明细")
        lines.append("")

        for cs in data.by_currency:
            lines.append(f"### {cs.currency}")
            lines.append("")
            lines.append("| 指标 | 值 |")
            lines.append("|---|---|")
            qty_parts = [f"{cs.total_quantity:,}"]
            if cs.for_cancellation > 0:
                qty_parts.append("(C)")
            if cs.for_treasury > 0:
                qty_parts.append("(T)")
            qty_display = " ".join(qty_parts)

            lines.append(f"| 回购数量 | {qty_display} |")
            lines.append(f"| 回购金额 | {cs.total_amount:,.2f} |")
            lines.append(f"| 价格区间 | {cs.low_price:,.2f} – {cs.high_price:,.2f} |")
            lines.append("")

        # 参考链接
        lines.append("## 参考链接")
        lines.append("")
        if data.document_urls:
            for url in data.document_urls:
                lines.append(f"{url}")
            lines.append("")

        return "\n".join(lines)


# ── 门面类 ──


class SingleCompanyDailySummary:
    """单公司每日回购摘要主类，协调数据获取、聚合和 Markdown 渲染。"""

    def __init__(
        self,
        fetcher: DataFetcher | None = None,
        aggregator: DataAggregator | None = None,
        renderer: Renderer | None = None,
    ) -> None:
        self._fetcher = fetcher or DataFetcher()
        self._aggregator = aggregator or DataAggregator()
        self._renderer = renderer or Renderer()
        self._data: CompanyDailyData | None = None

    @property
    def data(self) -> CompanyDailyData | None:
        return self._data

    def load(self, stock_code: str, trade_date: date) -> None:
        """加载指定股票在指定交易日的回购数据并聚合。"""
        records = self._fetcher.fetch(stock_code, trade_date)
        if not records:
            self._data = None
            return

        stock_name = self._fetcher.fetch_stock_name(stock_code)
        by_currency, cumulative_quantity, cumulative_pct, document_urls = self._aggregator.aggregate(records)

        self._data = CompanyDailyData(
            stock_code=stock_code,
            stock_name=stock_name,
            trade_date=trade_date,
            by_currency=by_currency,
            cumulative_quantity=cumulative_quantity,
            cumulative_pct=cumulative_pct,
            document_urls=document_urls,
        )

    def to_markdown(self) -> str:
        """导出为 Markdown 字符串。"""
        if not self._data:
            return ""
        return self._renderer.render(self._data)
