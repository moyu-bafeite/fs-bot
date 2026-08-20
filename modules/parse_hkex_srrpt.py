"""港交所股份回购报告（SRRPT）解析器。

解析 HKEX 每日发布的 Share Repurchase Report（.xls 格式），
提供原始记录提取、按公司+股票类型汇总、rich 表格展示和 JSON/CSV 导出。
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

import xlrd
from rich.console import Console
from rich.table import Table

# ── 数据模型 ──


@dataclass(frozen=True)
class RepurchaseRecord:
    """单笔回购原始记录。"""

    company: str
    stock_code: str
    sec_type: str
    trade_date: str
    quantity: int
    high_price: float
    low_price: float
    currency: str
    amount: float
    method: str
    total_repurchased: float
    for_cancellation: float
    for_treasury: float
    under_mandate: float
    pct_of_issued: float | None


@dataclass
class CompanySummary:
    """按公司+股票类型汇总的回购数据。"""

    company: str
    stock_code: str
    sec_type: str
    currency: str
    trade_dates: list[str]
    num_trades: int
    total_quantity: float
    avg_high_price: float
    avg_low_price: float
    total_amount: float
    method: str
    total_repurchased: float
    for_cancellation: float
    for_treasury: float
    under_mandate: float
    pct_of_issued: float | None


# ── 内部工具 ──


_CURRENCY_RE = re.compile(r"^(HKD|RMB|GBP|USD)\s*")


def _parse_amount(raw: str | None) -> tuple[float, str]:
    """从 'HKD 1,234.56' 样式字符串提取 (数值, 币种)。"""
    if not raw:
        return 0.0, ""
    s = str(raw).strip()
    m = _CURRENCY_RE.match(s)
    currency = m.group(1) if m else ""
    s = _CURRENCY_RE.sub("", s).replace(",", "")
    try:
        return float(s), currency
    except ValueError:
        return 0.0, currency


def _parse_int(raw: str | None) -> int:
    if not raw:
        return 0
    s = str(raw).strip().replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        return 0


def _parse_float(raw: str | None) -> float | None:
    if not raw:
        return None
    s = str(raw).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# ── 解析器 ──


class HKEXSrrptParser:
    """港交所股份回购报告 .xls 文件解析器。

    用法::

        parser = HKEXSrrptParser("SRRPT20260820.xls")
        parser.load()

        # 原始记录
        for rec in parser.records:
            print(rec.company, rec.amount)

        # 按公司汇总
        for s in parser.summaries:
            print(s.company, s.total_amount)

        # 渲染表格
        parser.print()

        # 导出
        json_str = parser.to_json()
        csv_str = parser.to_csv()
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._records: list[RepurchaseRecord] = []
        self._summaries: list[CompanySummary] = []
        self._report_date: str = ""

    @property
    def path(self) -> Path:
        return self._path

    @property
    def report_date(self) -> str:
        """报告发布日期，如 '2026-08-20'。"""
        return self._report_date

    @property
    def records(self) -> list[RepurchaseRecord]:
        """原始回购记录列表。"""
        return self._records

    @property
    def summaries(self) -> list[CompanySummary]:
        """按公司+股票类型汇总的列表，按总金额降序。"""
        return self._summaries

    # ── 核心工作流 ──

    def load(self) -> None:
        """读取 .xls 文件，解析原始记录并生成汇总。"""
        wb = xlrd.open_workbook(str(self._path))
        ws = wb.sheet_by_index(0)

        self._report_date = self._extract_report_date(ws)
        self._records = self._parse_rows(ws)
        self._summaries = self._aggregate(self._records)

    # ── 提取层 ──

    @staticmethod
    def _extract_report_date(ws: xlrd.sheet.Sheet) -> str:
        """从 'Date Printed : 20/08/2026' 行提取日期并转为 ISO 格式。"""
        for r in range(min(ws.nrows, 10)):
            for c in range(ws.ncols):
                val = ws.cell_value(r, c)
                if isinstance(val, str) and "Date Printed" in val:
                    raw = val.split(":", 1)[1].strip()  # '20/08/2026'
                    parts = raw.split("/")
                    if len(parts) == 3:
                        return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return ""

    @staticmethod
    def _parse_rows(ws: xlrd.sheet.Sheet) -> list[RepurchaseRecord]:
        """逐行解析数据区域（表头之后到 End Of Report 之前）。"""
        records: list[RepurchaseRecord] = []

        # 找到表头行（包含 'Company' 的行）
        header_row = -1
        for r in range(min(ws.nrows, 10)):
            if ws.cell_value(r, 0) == "Company":
                header_row = r
                break
        if header_row < 0:
            return records

        for r in range(header_row + 1, ws.nrows):
            company = ws.cell_value(r, 0)
            if not company or not isinstance(company, str):
                continue
            company = company.strip()
            if not company or company.startswith("***") or company.startswith("Whilst"):
                break
            if company.startswith("Note:") or company.startswith("Note :") or company.startswith("* "):
                continue

            stock_code_raw = ws.cell_value(r, 1)
            stock_code = str(stock_code_raw).strip()
            if stock_code.endswith(".0"):
                stock_code = stock_code[:-2]
            stock_code = stock_code.zfill(5)

            sec_type = str(ws.cell_value(r, 2)).strip()
            trade_date = str(ws.cell_value(r, 3)).strip().replace("/", "-")
            quantity = _parse_int(ws.cell_value(r, 4))

            high_price, _ = _parse_amount(ws.cell_value(r, 5))
            low_price, _ = _parse_amount(ws.cell_value(r, 6))
            amount, currency = _parse_amount(ws.cell_value(r, 7))

            method = str(ws.cell_value(r, 8)).strip()
            total_repurchased = _parse_int(ws.cell_value(r, 9))
            for_cancellation = _parse_int(ws.cell_value(r, 10))
            for_treasury = _parse_int(ws.cell_value(r, 11))
            under_mandate = _parse_int(ws.cell_value(r, 12))
            pct_of_issued = _parse_float(ws.cell_value(r, 13))

            records.append(
                RepurchaseRecord(
                    company=company,
                    stock_code=stock_code,
                    sec_type=sec_type,
                    trade_date=trade_date,
                    quantity=quantity,
                    high_price=high_price,
                    low_price=low_price,
                    currency=currency,
                    amount=amount,
                    method=method,
                    total_repurchased=total_repurchased,
                    for_cancellation=for_cancellation,
                    for_treasury=for_treasury,
                    under_mandate=under_mandate,
                    pct_of_issued=pct_of_issued,
                )
            )

        return records

    @staticmethod
    def _aggregate(records: list[RepurchaseRecord]) -> list[CompanySummary]:
        """按 (company, stock_code, sec_type, currency) 聚合。"""
        buckets: dict[tuple[str, str, str, str], list[RepurchaseRecord]] = {}
        for rec in records:
            key = (rec.company, rec.stock_code, rec.sec_type, rec.currency)
            buckets.setdefault(key, []).append(rec)

        summaries: list[CompanySummary] = []
        for (company, code, stype, cur), recs in buckets.items():
            dates = sorted({r.trade_date for r in recs})
            qty_values = [r.quantity for r in recs]
            total_qty = sum(qty_values)

            total_cancel = max((r.for_cancellation for r in recs), default=0)
            total_treasury = max((r.for_treasury for r in recs), default=0)
            max_mandate = max((r.under_mandate for r in recs), default=0)
            pct_values = [r.pct_of_issued for r in recs if r.pct_of_issued is not None]
            max_pct = max(pct_values) if pct_values else None

            # 回购方式：多笔可能在不同交易所，合并去重
            methods = list(dict.fromkeys(r.method for r in recs))
            method_str = " / ".join(methods)

            # 价格区间：取所有交易的最高价和最低价
            high_values = [r.high_price for r in recs if r.high_price > 0]
            low_values = [r.low_price for r in recs if r.low_price > 0]
            max_high = max(high_values) if high_values else 0.0
            min_low = min(low_values) if low_values else 0.0

            summaries.append(
                CompanySummary(
                    company=company,
                    stock_code=code,
                    sec_type=stype,
                    currency=cur,
                    trade_dates=dates,
                    num_trades=len(recs),
                    total_quantity=total_qty,
                    avg_high_price=max_high,
                    avg_low_price=min_low,
                    total_amount=sum(r.amount for r in recs),
                    method=method_str,
                    total_repurchased=max(
                        (r.total_repurchased for r in recs), default=0
                    ),
                    for_cancellation=total_cancel,
                    for_treasury=total_treasury,
                    under_mandate=max_mandate,
                    pct_of_issued=max_pct,
                )
            )

        summaries.sort(key=lambda s: s.total_amount, reverse=True)
        return summaries

    # ── 展示层 ──

    def print(self, console: Console | None = None) -> None:
        """按币种分组打印 rich 表格。"""
        con = console or Console(width=150)
        con.print(f"[bold]港交所股份回购报告 — {self._report_date}[/bold]")
        con.print(
            f"共 {len(self._summaries)} 个公司+股票类型组合，{len(self._records)} 笔回购\n"
        )

        currencies = list(dict.fromkeys(s.currency for s in self._summaries))

        for cur in currencies:
            group = [s for s in self._summaries if s.currency == cur]
            if not group:
                continue

            table = Table(
                title=f"币种: {cur}",
                show_header=True,
                header_style="bold cyan",
                border_style="dim",
                pad_edge=False,
            )
            table.add_column("公司", min_width=16)
            table.add_column("代码", justify="right")
            table.add_column("类型")
            table.add_column("交易日")
            table.add_column("笔", justify="right")
            table.add_column("回购数量", justify="right")
            table.add_column("价格区间", justify="right")
            table.add_column("总金额", justify="right")
            table.add_column("注销 / 库存", justify="right")
            table.add_column("本轮累计回购", justify="right")
            table.add_column("本轮累计占比 (%)", justify="right")

            for s in group:
                pct_str = (
                    f"{s.pct_of_issued:.2f}" if s.pct_of_issued is not None else "—"
                )
                mandate_str = f"{s.under_mandate:,}" if s.under_mandate > 0 else "—"
                dates_str = ", ".join(s.trade_dates)

                # 注销/库存股合并显示（注销为绿色）
                if s.for_cancellation > 0 and s.for_treasury > 0:
                    cancel_treasury_str = f"[green]注销{s.for_cancellation:,}[/green]/库存{s.for_treasury:,}"
                elif s.for_cancellation > 0:
                    cancel_treasury_str = f"[green]{s.for_cancellation:,} (注)[/green]"
                elif s.for_treasury > 0:
                    cancel_treasury_str = f"{s.for_treasury:,} (存)"
                else:
                    cancel_treasury_str = "—"

                # 价格区间：低价~高价，相同则只显示一个，去掉尾部多余的 0
                if s.avg_low_price > 0 and s.avg_high_price > 0:
                    lo = f"{s.avg_low_price:.4f}".rstrip("0").rstrip(".")
                    hi = f"{s.avg_high_price:.4f}".rstrip("0").rstrip(".")
                    if abs(s.avg_low_price - s.avg_high_price) < 0.0001:
                        price_str = lo
                    else:
                        price_str = f"{lo}~{hi}"
                else:
                    price_str = "—"

                table.add_row(
                    s.company,
                    s.stock_code,
                    s.sec_type,
                    dates_str,
                    str(s.num_trades),
                    f"{s.total_quantity:,}",
                    price_str,
                    f"{s.total_amount:,.2f}",
                    cancel_treasury_str,
                    mandate_str,
                    pct_str,
                )

            con.print(table)
            con.print()

    # ── 导出层 ──

    def _record_to_dict(self, rec: RepurchaseRecord) -> dict[str, object]:
        """单条原始记录转字典。"""
        return {
            "report_date": self._report_date,
            "company": rec.company,
            "stock_code": rec.stock_code,
            "sec_type": rec.sec_type,
            "trade_date": rec.trade_date,
            "quantity": rec.quantity,
            "high_price": rec.high_price,
            "low_price": rec.low_price,
            "currency": rec.currency,
            "amount": rec.amount,
            "method": rec.method,
            "total_repurchased": rec.total_repurchased,
            "for_cancellation": rec.for_cancellation,
            "for_treasury": rec.for_treasury,
            "under_mandate": rec.under_mandate,
            "pct_of_issued": rec.pct_of_issued,
        }

    def to_dict_list(self) -> list[dict[str, object]]:
        """原始记录转为字典列表。"""
        return [self._record_to_dict(r) for r in self._records]

    def to_json(self, indent: int = 2) -> str:
        """导出原始记录为 JSON 字符串。"""
        return json.dumps(self.to_dict_list(), ensure_ascii=False, indent=indent)

    def to_csv(self) -> str:
        """导出原始记录为 CSV 字符串。"""
        output = io.StringIO()
        fields = [
            "report_date",
            "company",
            "stock_code",
            "sec_type",
            "trade_date",
            "quantity",
            "high_price",
            "low_price",
            "currency",
            "amount",
            "method",
            "total_repurchased",
            "for_cancellation",
            "for_treasury",
            "under_mandate",
            "pct_of_issued",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(self.to_dict_list())
        return output.getvalue()

    def save_json(self, path: str | Path, indent: int = 2) -> Path:
        """导出 JSON 到文件，返回文件路径。"""
        p = Path(path)
        p.write_text(self.to_json(indent), encoding="utf-8")
        return p

    def save_csv(self, path: str | Path) -> Path:
        """导出 CSV 到文件，返回文件路径。"""
        p = Path(path)
        p.write_text(self.to_csv(), encoding="utf-8")
        return p
