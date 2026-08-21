"""港交所股份回购报告（SRRPT）解析器。

解析 HKEX 每日发布的 Share Repurchase Report（.xls 格式），
提供原始记录提取、按公司+股票类型汇总、rich 表格展示和 JSON/CSV 导出。

支持多套解析模板，通过列数自动检测：
- 旧格式 (11 列): 2024-06-10 及之前
- 新格式 (14 列): 2024-06-11 及之后
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


# ── 解析模板 ──


@dataclass(frozen=True)
class ColumnMapping:
    """列索引映射，None 表示该格式缺少此字段。"""

    company: int = 0
    stock_code: int = 1
    sec_type: int = 2
    trade_date: int = 3
    quantity: int = 4
    high_price: int = 5
    low_price: int = 6
    amount: int = 7
    method: int = 8
    total_repurchased: int | None = None
    for_cancellation: int | None = None
    for_treasury: int | None = None
    under_mandate: int | None = None
    pct_of_issued: int | None = None


class SrrptTemplate:
    """解析模板基类，定义列映射和格式检测。"""

    name: str = "base"
    column_count: int = 0
    mapping: ColumnMapping = ColumnMapping()

    @classmethod
    def matches(cls, ncols: int) -> bool:
        """判断是否匹配该模板。"""
        return ncols == cls.column_count

    @classmethod
    def extract_record(cls, ws: xlrd.sheet.Sheet, row: int) -> RepurchaseRecord:
        """从指定行提取一条记录。"""
        m = cls.mapping

        company = str(ws.cell_value(row, m.company)).strip()

        stock_code_raw = ws.cell_value(row, m.stock_code)
        stock_code = str(stock_code_raw).strip()
        if stock_code.endswith(".0"):
            stock_code = stock_code[:-2]
        stock_code = stock_code.zfill(5)

        sec_type = str(ws.cell_value(row, m.sec_type)).strip()
        trade_date = str(ws.cell_value(row, m.trade_date)).strip().replace("/", "-")
        quantity = _parse_int(ws.cell_value(row, m.quantity))

        high_price, _ = _parse_amount(ws.cell_value(row, m.high_price))
        low_price, _ = _parse_amount(ws.cell_value(row, m.low_price))
        amount, currency = _parse_amount(ws.cell_value(row, m.amount))

        method = str(ws.cell_value(row, m.method)).strip()

        # 可选字段，旧格式可能缺失
        total_repurchased = (
            _parse_int(ws.cell_value(row, m.total_repurchased))
            if m.total_repurchased is not None
            else quantity
        )
        for_cancellation = (
            _parse_int(ws.cell_value(row, m.for_cancellation))
            if m.for_cancellation is not None
            else quantity  # 旧格式全部强制注销
        )
        for_treasury = (
            _parse_int(ws.cell_value(row, m.for_treasury))
            if m.for_treasury is not None
            else 0
        )
        under_mandate = (
            _parse_int(ws.cell_value(row, m.under_mandate))
            if m.under_mandate is not None
            else 0
        )
        pct_of_issued = (
            _parse_float(ws.cell_value(row, m.pct_of_issued))
            if m.pct_of_issued is not None
            else None
        )

        # 价格缺失时用总金额 / 数量反算
        if high_price == 0 and low_price == 0 and quantity > 0 and amount > 0:
            high_price = low_price = round(amount / quantity, 4)
        # low_price 为 '-' 时（单一成交价），等于 high_price
        elif low_price == 0 and high_price > 0:
            low_price = high_price
        elif high_price == 0 and low_price > 0:
            high_price = low_price

        return RepurchaseRecord(
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


class OldTemplate(SrrptTemplate):
    """旧格式模板 (11 列): 2024-06-10 及之前。

    列布局:
    C0=Company  C1=Stock code  C2=Sec type  C3=Trade date
    C4=Quantity  C5=High price  C6=Low price  C7=Amount
    C8=Method  C9=Under mandate  C10=Pct of issued
    """

    name = "old"
    column_count = 11
    mapping = ColumnMapping(
        company=0,
        stock_code=1,
        sec_type=2,
        trade_date=3,
        quantity=4,
        high_price=5,
        low_price=6,
        amount=7,
        method=8,
        total_repurchased=None,
        for_cancellation=None,
        for_treasury=None,
        under_mandate=9,
        pct_of_issued=10,
    )


class OldTemplate12(SrrptTemplate):
    """旧格式变体 (12 列): 多一个空列 C8。

    列布局:
    C0=Company  C1=Stock code  C2=Sec type  C3=Trade date
    C4=Quantity  C5=High price  C6=Low price  C7=Amount
    C8=(空)  C9=Method  C10=Under mandate  C11=Pct of issued
    """

    name = "old12"
    column_count = 12
    mapping = ColumnMapping(
        company=0,
        stock_code=1,
        sec_type=2,
        trade_date=3,
        quantity=4,
        high_price=5,
        low_price=6,
        amount=7,
        method=9,
        total_repurchased=None,
        for_cancellation=None,
        for_treasury=None,
        under_mandate=10,
        pct_of_issued=11,
    )


class NewTemplate(SrrptTemplate):
    """新格式模板 (14 列): 2024-06-11 及之后。

    列布局:
    C0=Company  C1=Stock code  C2=Sec type  C3=Trade date
    C4=Quantity  C5=High price  C6=Low price  C7=Amount
    C8=Method  C9=Total repurchased  C10=For cancellation
    C11=For treasury  C12=Under mandate  C13=Pct of issued
    """

    name = "new"
    column_count = 14
    mapping = ColumnMapping(
        company=0,
        stock_code=1,
        sec_type=2,
        trade_date=3,
        quantity=4,
        high_price=5,
        low_price=6,
        amount=7,
        method=8,
        total_repurchased=9,
        for_cancellation=10,
        for_treasury=11,
        under_mandate=12,
        pct_of_issued=13,
    )


# 已注册模板列表（按优先级排序）
_TEMPLATES: list[type[SrrptTemplate]] = [NewTemplate, OldTemplate, OldTemplate12]


def register_template(template_cls: type[SrrptTemplate]) -> None:
    """注册自定义解析模板。"""
    _TEMPLATES.append(template_cls)


def detect_template(ws: xlrd.sheet.Sheet) -> type[SrrptTemplate]:
    """根据工作表列数自动检测模板。"""
    ncols = ws.ncols
    for tpl in _TEMPLATES:
        if tpl.matches(ncols):
            return tpl
    raise ValueError(f"未找到匹配 {ncols} 列的解析模板")


# ── 内部工具 ──


_CURRENCY_RE = re.compile(r"^(HKD|RMB|GBP|USD|EUR|SGD)\s*")


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


# ── 跳过行判断 ──

_SKIP_PREFIXES = (
    "***",
    "Whilst",
    "* ",
    "Hong Kong public holiday",
    "Note",
    "note",
    "No information available",
    "(",
    "completed",
    "Completed",
    "PINESTONE",
)

# 决议案续行的常见开头短语
_NOTE_CONTINUATIONS = (
    "grant rights",
    "granted after",
    "grants rights",
    "or grant rights",
    "contracts as if",
    "contracts to purchase",
    "or contracts",
    "save that this authority",
    "subscribe for",
    "shares to be granted",
    "but during that period",
    "to the expiry",
    "rights to subscribe",
    "for, or to convert",
    "resolution refers",
)


def _should_skip(company: str) -> bool:
    """判断该行是否应跳过（注释、尾部声明等）。"""
    if not company:
        return True
    # 已知前缀
    if any(company.startswith(p) for p in _SKIP_PREFIXES):
        return True
    # 以小写字母开头（决议案续行）
    if company[0].islower():
        return True
    # 纯标点/特殊字符
    if not any(c.isalnum() for c in company):
        return True
    # 决议案续行短语
    cl = company.lower()
    if any(cl.startswith(p) for p in _NOTE_CONTINUATIONS):
        return True
    return False


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

    自定义模板::

        class MyTemplate(SrrptTemplate):
            name = "custom"
            column_count = 12
            mapping = ColumnMapping(...)

        register_template(MyTemplate)
        parser = HKEXSrrptParser("file.xls")
        parser.load()
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._records: list[RepurchaseRecord] = []
        self._summaries: list[CompanySummary] = []
        self._report_date: str = ""
        self._template_name: str = ""

    @property
    def path(self) -> Path:
        return self._path

    @property
    def report_date(self) -> str:
        """报告发布日期，如 '2026-08-20'。"""
        return self._report_date

    @property
    def template_name(self) -> str:
        """使用的模板名称。"""
        return self._template_name

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

        template = detect_template(ws)
        self._template_name = template.name
        self._report_date = self._extract_report_date(ws)
        self._records = self._parse_rows(ws, template)
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
    def _parse_rows(
        ws: xlrd.sheet.Sheet, template: type[SrrptTemplate]
    ) -> list[RepurchaseRecord]:
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
            if not company:
                continue
            if _should_skip(company):
                if company.startswith("***") or company.startswith("Whilst"):
                    break
                continue

            records.append(template.extract_record(ws, r))

        return records

    @staticmethod
    def _aggregate(records: list[RepurchaseRecord]) -> list[CompanySummary]:
        """按 (company, stock_code, sec_type, currency, trade_date) 聚合。"""
        buckets: dict[tuple[str, str, str, str, str], list[RepurchaseRecord]] = {}
        for rec in records:
            key = (
                rec.company,
                rec.stock_code,
                rec.sec_type,
                rec.currency,
                rec.trade_date,
            )
            buckets.setdefault(key, []).append(rec)

        summaries: list[CompanySummary] = []
        for (company, code, stype, cur, td), recs in buckets.items():
            total_qty = sum(r.quantity for r in recs)

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
                    trade_dates=[td],
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
            f"共 {len(self._summaries)} 个公司+股票类型组合，"
            f"{len(self._records)} 笔回购（模板: {self._template_name}）\n"
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
                    cancel_treasury_str = (
                        f"[green]注销{s.for_cancellation:,}[/green]"
                        f"/库存{s.for_treasury:,}"
                    )
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
