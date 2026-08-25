"""股价数据质量检查框架。

每个检查器实现 Checker 协议，通过 CHECKERS 列表注册。
新增检查只需定义一个类并加入 CHECKERS。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from rich.console import Console

_INPUT_DIR = Path("downloads/stock_price")


# ── 结果模型 ──────────────────────────────────────────────


@dataclass(frozen=True)
class Issue:
    """单条检查问题。"""

    stock_code: str
    checker: str
    level: str  # "error" | "warning"
    message: str


@dataclass
class CheckReport:
    """一次检查的汇总报告。"""

    files_checked: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")


# ── Checker 协议 ──────────────────────────────────────────


class Checker(Protocol):
    """检查器接口。"""

    name: str

    def check(
        self, stock_code: str, files: dict[str, list[dict]]
    ) -> list[Issue]:
        """对单只股票的所有复权数据执行检查。

        Args:
            stock_code: 股票代码
            files: {right_label: records_list}，如 {"NR": [...], "BR": [...]}

        Returns:
            发现的问题列表
        """
        ...


# ── 内置检查器 ────────────────────────────────────────────


class RecordCountChecker:
    """检查同一股票的 NR / BR 记录数是否一致。"""

    name = "record_count"

    def check(
        self, stock_code: str, files: dict[str, list[dict]]
    ) -> list[Issue]:
        if len(files) < 2:
            return []

        counts = {right: len(recs) for right, recs in files.items()}
        unique = set(counts.values())
        if len(unique) <= 1:
            return []

        detail = ", ".join(f"{r}={n}" for r, n in sorted(counts.items()))
        return [
            Issue(
                stock_code=stock_code,
                checker=self.name,
                level="warning",
                message=f"记录数不一致: {detail}",
            )
        ]


class DateGapChecker:
    """检查交易日序列中是否存在异常间隔（>5 个自然日的缺口）。"""

    name = "date_gap"

    _MAX_GAP_DAYS = 5

    def check(
        self, stock_code: str, files: dict[str, list[dict]]
    ) -> list[Issue]:
        from datetime import date, timedelta

        issues: list[Issue] = []
        for right, records in files.items():
            if len(records) < 2:
                continue
            dates = sorted(r["trade_date"] for r in records)
            for i in range(1, len(dates)):
                prev = date.fromisoformat(dates[i - 1])
                curr = date.fromisoformat(dates[i])
                gap = (curr - prev).days
                if gap > self._MAX_GAP_DAYS:
                    issues.append(
                        Issue(
                            stock_code=stock_code,
                            checker=self.name,
                            level="warning",
                            message=(
                                f"{right} 异常间隔: {dates[i-1]} → {dates[i]}"
                                f" ({gap}天)"
                            ),
                        )
                    )
        return issues


# ── 检查器注册表（新增检查器在此添加）──────────────────────

CHECKERS: list[Checker] = [
    RecordCountChecker(),
    # DateGapChecker(),
]


# ── 文件发现与运行 ────────────────────────────────────────


def _discover_files(
    file_arg: str | None,
) -> dict[str, dict[str, Path]]:
    """发现并按股票代码分组。

    Returns:
        {stock_code: {right_label: path}}
    """
    if not _INPUT_DIR.exists():
        return {}

    if file_arg:
        p = Path(file_arg)
        if not p.is_absolute():
            p = _INPUT_DIR / p
        if not p.exists():
            return {}
        paths = [p]
    else:
        paths = sorted(
            f for f in _INPUT_DIR.glob("*.json") if not f.name.startswith("_")
        )

    grouped: dict[str, dict[str, Path]] = {}
    for path in paths:
        stem = path.stem  # e.g. "00837_NR"
        parts = stem.split("_", 1)
        if len(parts) != 2:
            continue
        code, right = parts
        grouped.setdefault(code, {})[right] = path
    return grouped


def _load_records(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("records", [])


def _check_one(stock_code: str, right_files: dict[str, Path]) -> tuple[int, list[Issue]]:
    """加载并检查单只股票，返回 (文件数, 问题列表)。"""
    data: dict[str, list[dict]] = {}
    for right, path in right_files.items():
        data[right] = _load_records(path)

    issues: list[Issue] = []
    for checker in CHECKERS:
        issues.extend(checker.check(stock_code, data))

    return len(data), issues


def run_checks(
    file_arg: str | None = None,
    console: Console | None = None,
    max_workers: int = 8,
) -> CheckReport:
    """执行所有已注册的检查（多线程）。

    Args:
        file_arg: 指定文件名（如 "00837_NR.json"），None 则检查全部
        console: Rich Console 实例
        max_workers: 线程数
    """
    console = console or Console()
    grouped = _discover_files(file_arg)

    if not grouped:
        console.print("[yellow]未找到匹配的数据文件[/yellow]")
        return CheckReport()

    report = CheckReport()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_check_one, code, files): code
            for code, files in grouped.items()
        }
        for future in as_completed(futures):
            file_count, issues = future.result()
            report.files_checked += file_count
            report.issues.extend(issues)

    # 输出报告
    _print_report(report, console)
    return report


def _print_report(report: CheckReport, console: Console) -> None:
    if report.ok:
        console.print(
            f"[green]✓[/green] 检查通过"
            f" ({report.files_checked} 个文件)"
        )
        return

    for issue in report.issues:
        tag = "red" if issue.level == "error" else "yellow"
        icon = "✗" if issue.level == "error" else "⚠"
        console.print(
            f"[{tag}]{icon}[/{tag}] {issue.stock_code}"
            f" [{issue.checker}] {issue.message}"
        )

    console.print(
        f"\n[red]{report.error_count} 错误[/red], "
        f"[yellow]{report.warning_count} 警告[/yellow]"
        f" (共检查 {report.files_checked} 个文件)"
    )
