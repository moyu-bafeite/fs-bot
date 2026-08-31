"""single-company-weekly-summary 数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class DailyRepurchase:
    """单日单笔回购记录。"""

    trade_date: date
    quantity: int
    amount: float
    high_price: float
    low_price: float
    currency: str
    for_cancellation: int
    for_treasury: int
    cumulative_quantity: int
    cumulative_pct: float

    @property
    def avg_price(self) -> float:
        return self.amount / self.quantity if self.quantity > 0 else 0.0


@dataclass(frozen=True)
class DailyPrice:
    """单日行情（同时包含前复权和不复权数据）。"""

    trade_date: date
    # 不复权（用于与回购价对比、成交额）
    nr_open: float
    nr_high: float
    nr_low: float
    nr_close: float
    nr_volume: int
    nr_turnover: float
    # 前复权（用于计算涨跌幅）
    br_open: float
    br_close: float


@dataclass(frozen=True)
class RepurchaseCycle:
    """一轮回购计划（从 quantity == cumulative_quantity 起）。"""

    start_date: date
    records: list[DailyRepurchase] = field(default_factory=list)

    @property
    def total_quantity(self) -> int:
        return sum(r.quantity for r in self.records)

    @property
    def total_amount(self) -> float:
        return sum(r.amount for r in self.records)

    @property
    def latest_cumulative_quantity(self) -> int:
        if not self.records:
            return 0
        return max(r.cumulative_quantity for r in self.records)

    @property
    def latest_cumulative_pct(self) -> float:
        if not self.records:
            return 0.0
        return max(r.cumulative_pct for r in self.records)


@dataclass(frozen=True)
class WeeklyMetrics:
    """一周计算出的指标。"""

    # 回购活动
    repurchase_days: int
    total_quantity: int
    total_amount: float
    avg_price: float
    cancellation_ratio: float

    # 回购力度
    turnover_ratio: float  # 回购数量 / 周成交量
    price_position: float  # 回购均价在 high-low 区间中的位置 (0~1)

    # 价格表现
    weekly_return: float     # 周涨跌幅（前复权）
    weekly_amplitude: float  # 周振幅
    weekly_turnover: float   # 周成交额（不复权）

    # 回购节奏
    cycle_total_quantity: int     # 本轮累计回购数量
    cycle_latest_pct: float       # 本轮累计占比
    weekly_quantity_ratio: float  # 本周回购数量 / 本轮累计数量


@dataclass(frozen=True)
class WeeklyReport:
    """最终报告数据。"""

    stock_code: str
    stock_name: dict[str, str]
    week_start: date
    week_end: date

    daily_repurchases: list[DailyRepurchase]
    daily_prices: list[DailyPrice]
    cycle: RepurchaseCycle
    metrics: WeeklyMetrics
