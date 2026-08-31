"""渲染 Markdown 报告。"""

from __future__ import annotations

from datetime import date

from modules.analysis.single_company_weekly_summary.models import (
    DailyRepurchase,
    RepurchaseCycle,
    WeeklyMetrics,
    WeeklyReport,
)


class Renderer:
    """将 WeeklyReport 渲染为 Markdown 文本。"""

    def render(self, report: WeeklyReport) -> str:
        sections = [
            self._header(report),
            self._summary(report),
            self._strength(report.metrics),
            self._price(report.metrics),
            self._rhythm(report),
            self._intent(report.metrics),
            self._risks(report.metrics),
            self._conclusion(report.metrics),
        ]
        return "\n\n".join(sections) + "\n"

    # ── 各段落 ──

    def _header(self, r: WeeklyReport) -> str:
        name = r.stock_name.get("zh-CN") or r.stock_name.get("en") or r.stock_code
        return (
            f"## {r.stock_code} {name} — 周度回购分析\n\n"
            f"**报告期间**: {r.week_start} ~ {r.week_end}"
        )

    def _summary(self, r: WeeklyReport) -> str:
        m = r.metrics
        days = len({d.trade_date for d in r.daily_prices})
        cancel_label = self._cancel_label(r.daily_repurchases)
        cycle_pct = f"{r.cycle.latest_cumulative_pct:.2f}%" if r.cycle.latest_cumulative_pct > 0 else "—"

        lines = [
            "### 一、回购行为摘要",
            "",
            "| 项目 | 数值 |",
            "|------|------|",
            f"| 回购天数 | {m.repurchase_days} / {days} |",
            f"| 回购总量 | {m.total_quantity:,} 股 |",
            f"| 回购总额 | {self._fmt_amount(m.total_amount)} |",
            f"| 回购均价 | {m.avg_price:.2f} |",
            f"| 周收盘价（不复权） | {self._week_close(r):.2f} |",
            f"| 偏差 | {self._price_deviation(m, r):.1f}% |",
            f"| 注销占比 | {cancel_label} |",
            f"| 累计进度 | {r.cycle.latest_cumulative_quantity:,} 股（{cycle_pct}） |",
        ]
        return "\n".join(lines)

    def _strength(self, m: WeeklyMetrics) -> str:
        position_label = self._position_label(m.price_position)
        lines = [
            "### 二、回购力度分析",
            "",
            "| 指标 | 本周 | 本轮累计 | 判断 |",
            "|------|------|----------|------|",
            f"| 回购数量 | {m.total_quantity:,} 股 | {m.cycle_total_quantity:,} 股 | 本周占本轮 {m.weekly_quantity_ratio:.0%} |",
            f"| 回购/成交占比 | {m.turnover_ratio:.2%} | — | {self._turnover_judgment(m.turnover_ratio)} |",
            f"| 回购价格位置 | {m.price_position:.0%} | — | {position_label} |",
        ]
        return "\n".join(lines)

    def _price(self, m: WeeklyMetrics) -> str:
        lines = [
            "### 三、价格表现",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 周涨跌幅（前复权） | {m.weekly_return:+.2%} |",
            f"| 周振幅 | {m.weekly_amplitude:.2%} |",
            f"| 周成交额（不复权） | {self._fmt_amount(m.weekly_turnover)} |",
        ]
        return "\n".join(lines)

    def _rhythm(self, r: WeeklyReport) -> str:
        lines = [
            "### 四、回购节奏",
            "",
            f"本轮起点：{r.cycle.start_date}",
            "",
        ]

        # 收集所有行数据
        rows: list[tuple[str, str, str, str, str]] = []
        week_dates = {d.trade_date for d in r.daily_repurchases}

        for rec in r.cycle.records:
            pos = self._daily_price_position(rec)
            rows.append((
                str(rec.trade_date),
                f"{rec.quantity / 1e4:.1f}",
                self._fmt_amount(rec.amount),
                f"{pos:.0%}",
                self._position_bar(pos),
            ))

        if r.daily_repurchases:
            total_qty = sum(rec.quantity for rec in r.daily_repurchases) / 1e4
            total_amt = sum(rec.amount for rec in r.daily_repurchases)
            total_q = sum(rec.quantity for rec in r.daily_repurchases)
            avg_pos = sum(
                self._daily_price_position(rec) * rec.quantity
                for rec in r.daily_repurchases
            )
            avg_pos = avg_pos / total_q if total_q > 0 else 0
            rows.append((
                "本周合计",
                f"{total_qty:.1f}",
                self._fmt_amount(total_amt),
                f"{avg_pos:.0%}",
                self._position_bar(avg_pos),
            ))

        # 计算列宽
        headers = ("日期", "数量（万股）", "金额", "价格位置", "图示")
        col_widths = [
            max(len(h), max((len(row[i]) for row in rows), default=0))
            for i, h in enumerate(headers)
        ]

        # 渲染 Markdown 表格
        def _fmt_row(cells: tuple[str, ...]) -> str:
            left = f"| {cells[0]:<{col_widths[0]}} "
            rest = " ".join(
                f"| {cells[i]:>{col_widths[i]}} " for i in range(1, len(cells))
            )
            return f"{left}{rest}|"

        lines.append(_fmt_row(headers))
        lines.append(
            "| " + " | ".join("-" * w for w in col_widths) + " |"
        )
        for row in rows:
            lines.append(_fmt_row(row))

        return "\n".join(lines)

    def _intent(self, m: WeeklyMetrics) -> str:
        signals: list[str] = []

        if m.price_position < 0.3 and m.weekly_quantity_ratio > 0.3:
            signals.append("价格位置 <30% + 本周回购占比较高 — 低位加速扫货")
        elif m.price_position > 0.7:
            signals.append("价格位置 >70% — 回购价位偏高，可能接近管理层心理价位")

        if m.repurchase_days == 5:
            signals.append("本周 5 天全部回购 — 态度坚决")
        elif m.repurchase_days >= 4:
            signals.append(f"本周 {m.repurchase_days} 天回购 — 节奏稳定")

        if m.cancellation_ratio >= 0.9:
            signals.append("注销比例高 — 真正减少流通股")
        elif m.cancellation_ratio < 0.5 and m.cancellation_ratio > 0:
            signals.append("注销比例低 — 可能是股权激励储备")

        if not signals:
            signals.append("回购力度温和，无明显信号")

        items = "\n".join(f"- {s}" for s in signals)
        return f"### 五、管理层意图判断\n\n{items}"

    def _risks(self, m: WeeklyMetrics) -> str:
        risks: list[str] = []

        if m.weekly_return > 0 and m.repurchase_days > 0:
            risks.append("本周股价上涨，回购未能阻止上涨 — 若持续上涨，管理层可能放缓节奏")

        if m.turnover_ratio > 0.1:
            risks.append(f"回购/成交占比 {m.turnover_ratio:.1%}，较高 — 短期流动性被消耗")

        if m.cycle_latest_pct > 0.8:
            risks.append(f"累计进度 {m.cycle_latest_pct:.0%}，本轮计划接近尾声")

        if not risks:
            risks.append("暂无明显风险")

        items = "\n".join(f"- {r}" for r in risks)
        return f"### 六、风险提示\n\n{items}"

    def _conclusion(self, m: WeeklyMetrics) -> str:
        if m.price_position < 0.35 and m.turnover_ratio > 0.03 and m.cancellation_ratio > 0.8:
            verdict = "管理层在相对低位持续回购并注销，态度偏正面"
        elif m.price_position > 0.65:
            verdict = "回购价位偏高，管理层态度有待观察"
        elif m.turnover_ratio < 0.01:
            verdict = "回购力度温和，信号较弱"
        else:
            verdict = "回购稳步推进，态度中性"

        return f"**结论**: {verdict}。"

    # ── 辅助方法 ──

    def _week_close(self, r: WeeklyReport) -> float:
        if not r.daily_prices:
            return 0.0
        return r.daily_prices[-1].nr_close

    def _price_deviation(self, m: WeeklyMetrics, r: WeeklyReport) -> float:
        close = self._week_close(r)
        if close <= 0 or m.avg_price <= 0:
            return 0.0
        return (m.avg_price - close) / close * 100

    def _cancel_label(self, repurchases: list[DailyRepurchase]) -> str:
        total_cancel = sum(r.for_cancellation for r in repurchases)
        total_treasury = sum(r.for_treasury for r in repurchases)
        total = total_cancel + total_treasury
        if total == 0:
            return "—"
        pct = total_cancel / total
        if pct >= 0.9:
            return f"100% 注销 (C)"
        if pct <= 0.1:
            return f"100% 库存 (T)"
        return f"{pct:.0%} 注销 / {1 - pct:.0%} 库存"

    def _position_label(self, position: float) -> str:
        if position < 0.3:
            return "低位扫货"
        if position < 0.5:
            return "偏低位买入"
        if position < 0.7:
            return "中位买入"
        return "偏高位买入"

    def _turnover_judgment(self, ratio: float) -> str:
        if ratio > 0.1:
            return "力度强"
        if ratio > 0.03:
            return "力度温和"
        return "力度弱"

    def _daily_price_position(self, rec: DailyRepurchase) -> float:
        spread = rec.high_price - rec.low_price
        if spread <= 0:
            return 0.5
        return (rec.avg_price - rec.low_price) / spread

    @staticmethod
    def _fmt_amount(value: float) -> str:
        """格式化金额：HKD 445.5M / HKD 1.50B。"""
        if value >= 1e9:
            return f"HKD {value / 1e9:.2f}B"
        if value >= 1e6:
            return f"HKD {value / 1e6:.1f}M"
        if value >= 1e3:
            return f"HKD {value / 1e3:.1f}K"
        return f"HKD {value:.0f}"

    @staticmethod
    def _position_bar(position: float, width: int = 20) -> str:
        """生成价格位置图示：[────█──────────] 表示 25% 位置。"""
        pos = max(0.0, min(1.0, position))
        idx = round(pos * (width - 1))
        chars = list("─" * width)
        chars[idx] = "█"
        return "[" + "".join(chars) + "]"
