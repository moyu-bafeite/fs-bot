"""数据清洗、关联、分周。"""

from __future__ import annotations

from datetime import date
from typing import Any

from modules.analysis.single_company_weekly_summary.models import (
    DailyPrice,
    DailyRepurchase,
    RepurchaseCycle,
)


def parse_repurchase(records: list[dict[str, Any]]) -> list[DailyRepurchase]:
    """原始 dict → DailyRepurchase 列表，按 trade_date 排序。"""
    items = [
        DailyRepurchase(
            trade_date=date.fromisoformat(r["trade_date"]),
            quantity=int(r.get("quantity") or 0),
            amount=float(r.get("amount") or 0),
            high_price=float(r.get("high_price") or 0),
            low_price=float(r.get("low_price") or 0),
            currency=r.get("currency", ""),
            for_cancellation=int(r.get("for_cancellation") or 0),
            for_treasury=int(r.get("for_treasury") or 0),
            cumulative_quantity=int(r.get("cumulative_quantity") or 0),
            cumulative_pct=float(r.get("cumulative_pct") or 0),
        )
        for r in records
    ]
    items.sort(key=lambda x: x.trade_date)
    return items


def parse_prices(
    nr_records: list[dict[str, Any]],
    br_records: list[dict[str, Any]],
) -> list[DailyPrice]:
    """合并不复权和前复权数据为 DailyPrice 列表。"""
    br_map: dict[str, dict[str, Any]] = {
        r["trade_date"]: r for r in br_records
    }

    items: list[DailyPrice] = []
    for nr in nr_records:
        td = nr["trade_date"]
        br = br_map.get(td, {})
        items.append(
            DailyPrice(
                trade_date=date.fromisoformat(td),
                nr_open=float(nr.get("open") or 0),
                nr_high=float(nr.get("high") or 0),
                nr_low=float(nr.get("low") or 0),
                nr_close=float(nr.get("close") or 0),
                nr_volume=int(nr.get("volume") or 0),
                nr_turnover=float(nr.get("turnover") or 0),
                br_open=float(br.get("open") or 0),
                br_close=float(br.get("close") or 0),
            )
        )
    items.sort(key=lambda x: x.trade_date)
    return items


def detect_cycles(
    repurchases: list[DailyRepurchase],
) -> list[RepurchaseCycle]:
    """检测回购计划轮次。

    判定规则：quantity == cumulative_quantity 的记录为新一轮起点。
    """
    if not repurchases:
        return []

    cycles: list[RepurchaseCycle] = []
    current_records: list[DailyRepurchase] = []
    current_start = repurchases[0].trade_date

    for rec in repurchases:
        if rec.quantity == rec.cumulative_quantity and current_records:
            # 新一轮起点，收束上一轮
            cycles.append(RepurchaseCycle(start_date=current_start, records=current_records))
            current_records = []
            current_start = rec.trade_date
        current_records.append(rec)

    if current_records:
        cycles.append(RepurchaseCycle(start_date=current_start, records=current_records))

    return cycles


def filter_week_repurchases(
    repurchases: list[DailyRepurchase],
    week_start: date,
    week_end: date,
) -> list[DailyRepurchase]:
    """筛选指定日期区间内的回购记录。"""
    return [r for r in repurchases if week_start <= r.trade_date <= week_end]


def filter_week_prices(
    prices: list[DailyPrice],
    week_start: date,
    week_end: date,
) -> list[DailyPrice]:
    """筛选指定日期区间内的行情数据。"""
    return [p for p in prices if week_start <= p.trade_date <= week_end]


def find_containing_cycle(
    cycles: list[RepurchaseCycle],
    week_end: date,
) -> RepurchaseCycle | None:
    """找到包含 week_end 的回购轮次（该轮最后一条记录 >= week_end）。"""
    for cycle in reversed(cycles):
        if cycle.records and cycle.records[-1].trade_date >= week_end:
            return cycle
    # fallback: 返回最后一轮
    return cycles[-1] if cycles else None
