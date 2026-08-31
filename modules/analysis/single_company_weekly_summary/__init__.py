"""单公司周度回购分析。

用法::

    from modules.analysis.single_company_weekly_summary import WeeklySummary

    summary = WeeklySummary("00700", date(2026, 8, 29))
    print(summary.to_markdown())
"""

from __future__ import annotations

from datetime import date, timedelta

from modules.analysis.single_company_weekly_summary.fetcher import (
    fetch_br_prices,
    fetch_nr_prices,
    fetch_repurchase,
    fetch_stock_name,
)
from modules.analysis.single_company_weekly_summary.indicators import (
    calc_weekly_metrics,
)
from modules.analysis.single_company_weekly_summary.models import WeeklyReport
from modules.analysis.single_company_weekly_summary.preprocessor import (
    detect_cycles,
    filter_week_prices,
    filter_week_repurchases,
    find_containing_cycle,
    parse_prices,
    parse_repurchase,
)
from modules.analysis.single_company_weekly_summary.renderer import Renderer


class WeeklySummary:
    """单公司周度回购分析门面类。"""

    def __init__(self, stock_code: str, week_end: date) -> None:
        self._stock_code = stock_code
        self._week_end = week_end
        self._report: WeeklyReport | None = None
        self._renderer = Renderer()

    @property
    def report(self) -> WeeklyReport | None:
        return self._report

    def load(self) -> None:
        """获取数据 → 预处理 → 计算指标，生成报告。"""
        # 回购数据需要更长的历史区间来检测轮次
        cycle_start = date(self._week_end.year - 1, self._week_end.month, self._week_end.day)
        week_start = self._week_end - timedelta(days=self._week_end.weekday())

        # 获取原始数据
        rep_raw = fetch_repurchase(self._stock_code, cycle_start, self._week_end)
        nr_raw = fetch_nr_prices(self._stock_code, week_start, self._week_end)
        br_raw = fetch_br_prices(self._stock_code, week_start, self._week_end)
        stock_name = fetch_stock_name(self._stock_code)

        # 预处理
        all_rep = parse_repurchase(rep_raw)
        prices = parse_prices(nr_raw, br_raw)
        cycles = detect_cycles(all_rep)

        week_rep = filter_week_repurchases(all_rep, week_start, self._week_end)
        week_prices = filter_week_prices(prices, week_start, self._week_end)
        cycle = find_containing_cycle(cycles, self._week_end)

        # 计算指标
        metrics = calc_weekly_metrics(week_rep, week_prices, cycle)

        self._report = WeeklyReport(
            stock_code=self._stock_code,
            stock_name=stock_name,
            week_start=week_start,
            week_end=self._week_end,
            daily_repurchases=week_rep,
            daily_prices=week_prices,
            cycle=cycle,
            metrics=metrics,
        )

    def to_markdown(self) -> str:
        if not self._report:
            raise RuntimeError("请先调用 load() 加载数据")
        return self._renderer.render(self._report)
