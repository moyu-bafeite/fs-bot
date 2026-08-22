"""股价数据下载与增量合并。

从 Tiger API 获取日K线数据，支持检测已有文件的最大日期并只拉取增量部分。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from tigeropen.common.consts import QuoteRight

from lib.db import get_hk_stocks
from modules.stock_price.tiger_kline import TigerKlineFetcher

_DEFAULT_DIR = Path("downloads/stock_price")


@dataclass(frozen=True)
class DownloadResult:
    """单个文件的下载结果。"""

    stock_code: str
    right: str
    path: Path | None
    records_count: int
    success: bool
    error: str = ""


@dataclass
class StockPriceDownloader:
    """股价数据下载器，支持增量合并与进度展示。

    用法::

        dl = StockPriceDownloader(fetcher=TigerKlineFetcher())
        results = dl.download(
            tickers=["00700", "09988"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            rights=[QuoteRight.NR, QuoteRight.BR],
        )
    """

    fetcher: TigerKlineFetcher
    output_dir: Path = field(default_factory=lambda: _DEFAULT_DIR)
    console: Console = field(default_factory=Console)

    def download(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        rights: list[QuoteRight],
    ) -> list[DownloadResult]:
        """批量下载股价数据。

        Args:
            tickers: 股票代码列表，为空时从数据库获取全部活跃港股
            start_date: 起始日期
            end_date: 结束日期
            rights: 复权方式列表
        """
        if not tickers:
            self.console.print("未指定标的，从数据库获取全部活跃港股...")
            stocks = get_hk_stocks()
            tickers = [s["stock_code"] for s in stocks]
            self.console.print(f"共 {len(tickers)} 只股票")

        if not tickers:
            self.console.print("[yellow]无股票数据[/yellow]")
            return []

        self.output_dir.mkdir(parents=True, exist_ok=True)

        tasks: list[tuple[str, str, QuoteRight]] = []
        for ticker in tickers:
            for right in rights:
                label = right.value.upper()
                tasks.append((ticker, label, right))

        self.console.print(
            f"共 {len(tasks)} 个任务（{len(tickers)} 只股票 × {len(rights)} 种复权）"
        )

        results: list[DownloadResult] = []
        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task_id = progress.add_task("下载中", total=len(tasks))

            for ticker, label, right in tasks:
                progress.update(task_id, description=f"{ticker} ({label})")
                result = self._download_one(ticker, label, right, start_date, end_date)
                results.append(result)
                progress.advance(task_id)

        ok = sum(1 for r in results if r.success)
        skip = sum(1 for r in results if r.success and r.records_count == 0)
        fail = len(results) - ok
        self.console.print(f"完成: {ok - skip} 新增, {skip} 跳过, {fail} 失败")

        return results

    def _download_one(
        self,
        stock_code: str,
        right_label: str,
        right: QuoteRight,
        start_date: date,
        end_date: date,
    ) -> DownloadResult:
        """下载单个标的的一种复权数据，支持增量合并。"""
        file_path = self.output_dir / f"{stock_code}_{right_label}.json"

        effective_start = start_date
        existing_records: list[dict[str, Any]] = []

        if file_path.exists():
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                existing_records = data.get("records", [])
                if existing_records:
                    max_date_str = max(r["trade_date"] for r in existing_records)
                    max_date = date.fromisoformat(max_date_str)
                    effective_start = max_date + timedelta(days=1)
            except (json.JSONDecodeError, KeyError, ValueError):
                existing_records = []

        if effective_start > end_date:
            return DownloadResult(stock_code, right_label, file_path, 0, True)

        try:
            new_records = self.fetcher.fetch_daily(
                stock_code, effective_start, end_date, right
            )
        except Exception as e:
            return DownloadResult(stock_code, right_label, None, 0, False, str(e))

        merged = self._merge_records(existing_records, new_records)

        output = {
            "stock_code": stock_code,
            "right": right_label,
            "records": merged,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        return DownloadResult(stock_code, right_label, file_path, len(new_records), True)

    @staticmethod
    def _merge_records(
        existing: list[dict[str, Any]],
        new: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """合并新旧记录，按日期去重（新数据优先），按日期升序排列。"""
        seen: dict[str, dict[str, Any]] = {}
        for rec in existing:
            seen[rec["trade_date"]] = rec
        for rec in new:
            seen[rec["trade_date"]] = rec
        return sorted(seen.values(), key=lambda r: r["trade_date"])
