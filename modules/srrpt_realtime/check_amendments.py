"""检测翌日披露报表修订。

同一 (stock_code, trade_date, currency) 对应多个不同的 document_url，
说明公司发布了修订版报告。按 document_url 分组并比较字段差异。

不同 currency 的记录视为不同交易所的正常回购，不视为修订。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.table import Table

from lib.db.client import _md_client

_FIELDS_TO_COMPARE = [
    "report_date",
    "quantity",
    "high_price",
    "low_price",
    "amount",
    "method",
    "for_cancellation",
    "for_treasury",
    "cumulative_quantity",
    "cumulative_pct",
]


@dataclass
class VersionDiff:
    """单个字段的版本间差异。"""

    field_name: str
    values: list[Any]


@dataclass
class AmendmentGroup:
    """一组修订记录：同一 (stock_code, trade_date, currency) 下的多个版本。"""

    stock_code: str
    trade_date: str
    currency: str
    versions: list[dict[str, Any]]
    diffs: list[VersionDiff] = field(default_factory=list)


def _fetch_all_records() -> list[dict[str, Any]]:
    """分页拉取全部 realtime reports。"""
    records: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            _md_client.table("hkex_repurchase_realtime_reports")
            .select("*")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            break
        records.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return records


def _group_by_url(versions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按 document_url 分组。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for v in versions:
        url = v.get("document_url") or "(no url)"
        groups.setdefault(url, []).append(v)
    return groups


def _find_diffs(versions: list[dict[str, Any]]) -> list[VersionDiff]:
    """比较同组内各版本的字段值，返回有差异的字段。"""
    diffs: list[VersionDiff] = []
    for f in _FIELDS_TO_COMPARE:
        values = [v.get(f) for v in versions]
        unique = set()
        for val in values:
            if val is None:
                unique.add(None)
            elif isinstance(val, float):
                unique.add(round(val, 10))
            else:
                unique.add(val)
        if len(unique) > 1:
            diffs.append(VersionDiff(field_name=f, values=values))
    return diffs


def find_amendments(console: Console | None = None) -> list[AmendmentGroup]:
    """检测所有修订：同一 (stock_code, trade_date, currency) 存在多个 document_url。"""
    con = console or Console()
    con.print("正在拉取 hkex_repurchase_realtime_reports ...")
    records = _fetch_all_records()
    con.print(f"共 {len(records)} 条记录")

    # 按 (stock_code, trade_date, currency) 分组
    key_map: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for rec in records:
        key = (rec["stock_code"], rec["trade_date"], rec.get("currency") or "")
        key_map.setdefault(key, []).append(rec)

    # 筛选存在多个不同 document_url 的组
    amendments: list[AmendmentGroup] = []
    for (stock_code, trade_date, currency), versions in sorted(key_map.items()):
        url_groups = _group_by_url(versions)
        if len(url_groups) <= 1:
            continue
        diffs = _find_diffs(versions)
        amendments.append(
            AmendmentGroup(
                stock_code=stock_code,
                trade_date=trade_date,
                currency=currency,
                versions=versions,
                diffs=diffs,
            )
        )

    return amendments


def _fmt(val: Any) -> str:
    if val is None:
        return "-"
    if isinstance(val, float):
        return f"{val:,.4f}".rstrip("0").rstrip(".")
    return str(val)


def print_report(amendments: list[AmendmentGroup], console: Console | None = None) -> None:
    """打印修订检测报告。"""
    con = console or Console()

    if not amendments:
        con.print("[green]未发现修订记录[/green]")
        return

    con.print(f"\n[bold]发现 {len(amendments)} 组修订[/bold]\n")

    for group in amendments:
        header = f"[bold cyan]{group.stock_code}[/bold cyan]  trade_date={group.trade_date}  currency={group.currency}  ({len(group.versions)} 条记录, {len(group.versions) - 1} 次修订)"
        con.print(header)

        table = Table(show_header=True, header_style="bold", show_lines=True, padding=(0, 1))
        table.add_column("id", justify="right", style="dim")
        table.add_column("report_date")
        table.add_column("document_url", max_width=60)

        for f in _FIELDS_TO_COMPARE:
            is_diff = any(d.field_name == f for d in group.diffs)
            style = "bold red" if is_diff else None
            table.add_column(f, style=style)

        for v in group.versions:
            row = [
                str(v.get("id", "")),
                _fmt(v.get("report_date")),
                _fmt(v.get("document_url", "")),
            ]
            for f in _FIELDS_TO_COMPARE:
                row.append(_fmt(v.get(f)))
            table.add_row(*row)

        con.print(table)
        con.print()

    # 汇总
    total_versions = sum(len(g.versions) for g in amendments)
    total_diffs = sum(len(g.diffs) for g in amendments)
    con.print(f"[bold]汇总:[/bold] {len(amendments)} 组修订, {total_versions} 条记录, {total_diffs} 个字段差异")
