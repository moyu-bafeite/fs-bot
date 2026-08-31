"""计算所有指标，纯函数。"""

from __future__ import annotations

from modules.analysis.single_company_weekly_summary.models import (
    DailyPrice,
    DailyRepurchase,
    RepurchaseCycle,
    WeeklyMetrics,
)


def calc_weekly_metrics(
    week_repurchases: list[DailyRepurchase],
    week_prices: list[DailyPrice],
    cycle: RepurchaseCycle | None,
) -> WeeklyMetrics:
    """汇总一周数据，计算全部指标。"""
    # ── 回购活动 ──
    repurchase_days = len({r.trade_date for r in week_repurchases})
    total_quantity = sum(r.quantity for r in week_repurchases)
    total_amount = sum(r.amount for r in week_repurchases)
    avg_price = total_amount / total_quantity if total_quantity > 0 else 0.0

    total_cancel = sum(r.for_cancellation for r in week_repurchases)
    total_treasury = sum(r.for_treasury for r in week_repurchases)
    cancellation_ratio = total_cancel / (total_cancel + total_treasury) if (total_cancel + total_treasury) > 0 else 0.0

    # ── 回购力度 ──
    week_volume = sum(p.nr_volume for p in week_prices)
    turnover_ratio = total_quantity / week_volume if week_volume > 0 else 0.0

    price_position = _calc_price_position(week_repurchases)

    # ── 价格表现 ──
    weekly_return = _calc_weekly_return(week_prices)
    weekly_amplitude = _calc_weekly_amplitude(week_prices)
    weekly_turnover = sum(p.nr_turnover for p in week_prices)

    # ── 回购节奏 ──
    cycle_total = cycle.total_quantity if cycle else 0
    cycle_pct = cycle.latest_cumulative_pct if cycle else 0.0
    weekly_qty_ratio = total_quantity / cycle_total if cycle_total > 0 else 0.0

    return WeeklyMetrics(
        repurchase_days=repurchase_days,
        total_quantity=total_quantity,
        total_amount=total_amount,
        avg_price=avg_price,
        cancellation_ratio=cancellation_ratio,
        turnover_ratio=turnover_ratio,
        price_position=price_position,
        weekly_return=weekly_return,
        weekly_amplitude=weekly_amplitude,
        weekly_turnover=weekly_turnover,
        cycle_total_quantity=cycle_total,
        cycle_latest_pct=cycle_pct,
        weekly_quantity_ratio=weekly_qty_ratio,
    )


def _calc_price_position(repurchases: list[DailyRepurchase]) -> float:
    """回购均价在 high-low 区间中的位置 (0~1)。

    按数量加权计算每日位置，再取加权平均。
    """
    if not repurchases:
        return 0.0

    weighted_sum = 0.0
    weight_total = 0

    for r in repurchases:
        spread = r.high_price - r.low_price
        if spread <= 0 or r.quantity <= 0:
            continue
        position = (r.avg_price - r.low_price) / spread
        weighted_sum += position * r.quantity
        weight_total += r.quantity

    return weighted_sum / weight_total if weight_total > 0 else 0.0


def _calc_weekly_return(prices: list[DailyPrice]) -> float:
    """周涨跌幅（前复权）。"""
    if len(prices) < 2:
        return 0.0
    first_open = prices[0].br_open
    last_close = prices[-1].br_close
    if first_open <= 0:
        return 0.0
    return (last_close - first_open) / first_open


def _calc_weekly_amplitude(prices: list[DailyPrice]) -> float:
    """周振幅 = (周最高 - 周最低) / 周一开盘。"""
    if not prices:
        return 0.0
    week_high = max(p.nr_high for p in prices)
    week_low = min(p.nr_low for p in prices)
    first_open = prices[0].nr_open
    if first_open <= 0:
        return 0.0
    return (week_high - week_low) / first_open
