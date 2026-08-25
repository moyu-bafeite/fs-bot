"""股价数据上传器：将本地 JSON 文件上传到 Supabase。

流式设计：分批读取文件，按复权类型分桶，桶满即 flush，控制内存峰值。
"""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from lib.db import upsert_br_daily_prices, upsert_nr_daily_prices

_INPUT_DIR = Path("downloads/stock_price")

_UPSERT_MAP = {
    "BR": upsert_br_daily_prices,
    "NR": upsert_nr_daily_prices,
}


@dataclass(frozen=True)
class UploadResult:
    """上传结果。"""

    right: str
    files_count: int
    records_count: int
    success: bool
    error: str = ""


@dataclass(frozen=True)
class _FileData:
    """单个文件的解析结果。"""

    file: Path
    right: str
    rows: list[dict]


@dataclass(frozen=True)
class _ReadError:
    """文件读取失败。"""

    file: Path
    error: str


@dataclass
class StockPriceUploader:
    """股价数据上传器（流式处理，控制内存峰值）。

    用法::

        uploader = StockPriceUploader()
        results = uploader.upload(tickers=["00700", "09988"])
    """

    console: Console = field(default_factory=Console)
    max_workers: int = 8
    read_batch_size: int = 50
    flush_threshold: int = 10_000

    def upload(
        self,
        tickers: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        dry_run: bool = False,
    ) -> list[UploadResult]:
        """流式上传 JSON 文件到 Supabase。

        Args:
            tickers: 股票代码列表，为空或 None 时上传全部
            start_date: 只上传 trade_date >= start_date 的记录
            end_date: 只上传 trade_date <= end_date 的记录
            dry_run: 仅打印，不实际上传
        """
        files = self._discover_files(tickers)
        if not files:
            self.console.print("[yellow]WARNING: 无待上传文件[/yellow]")
            return []

        self.console.print(
            f"待上传 {len(files)} 个文件 "
            f"(读取批次: {self.read_batch_size}, flush 阈值: {self.flush_threshold})"
        )
        if dry_run:
            self.console.print("[yellow]DRY RUN 模式[/yellow]")

        # 按复权类型分桶的累计数据
        buckets: dict[str, list[dict]] = defaultdict(list)
        bucket_file_counts: dict[str, int] = defaultdict(int)
        results: list[UploadResult] = []
        total_read_errors = 0

        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task_id = progress.add_task("读取文件", total=len(files))

            # 分批读取
            for batch_start in range(0, len(files), self.read_batch_size):
                batch = files[batch_start : batch_start + self.read_batch_size]
                file_data_list, read_errors = self._read_batch(
                    batch, start_date, end_date
                )

                total_read_errors += len(read_errors)
                for err in read_errors:
                    self.console.print(
                        f"[red]✗ 读取失败[/red] {err.file.name}: {err.error}"
                    )

                # 累积到桶
                for fd in file_data_list:
                    buckets[fd.right].extend(fd.rows)
                    bucket_file_counts[fd.right] += 1

                progress.advance(task_id, advance=len(batch))

                # 检查是否需要 flush
                flush_results, buckets, bucket_file_counts = self._flush_full_buckets(
                    buckets, bucket_file_counts, dry_run
                )
                results.extend(flush_results)

        # flush 剩余数据
        flush_results, _, _ = self._flush_all(buckets, bucket_file_counts, dry_run)
        results.extend(flush_results)

        if total_read_errors:
            self.console.print(f"[yellow]读取失败: {total_read_errors} 个文件[/yellow]")

        total = sum(r.records_count for r in results if r.success)
        fail = sum(1 for r in results if not r.success)
        self.console.print(f"\n完成: {total} 条记录, {fail} 组失败")

        return results

    def _discover_files(self, tickers: list[str] | None) -> list[Path]:
        """根据 tickers 筛选待上传的 JSON 文件。"""
        if not _INPUT_DIR.exists():
            return []
        if tickers:
            prefixes = set(tickers)
            return sorted(
                f for f in _INPUT_DIR.glob("*.json")
                if not f.name.startswith("_")
                and f.stem.split("_")[0] in prefixes
            )
        return sorted(
            f for f in _INPUT_DIR.glob("*.json") if not f.name.startswith("_")
        )

    def _read_batch(
        self,
        files: list[Path],
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[list[_FileData], list[_ReadError]]:
        """多线程并行读取一批文件。"""
        ok: list[_FileData] = []
        errors: list[_ReadError] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._read_file, file, start_date, end_date
                ): file
                for file in files
            }
            for future in as_completed(futures):
                result = future.result()
                if isinstance(result, _FileData):
                    ok.append(result)
                else:
                    errors.append(result)

        return ok, errors

    def _flush_full_buckets(
        self,
        buckets: dict[str, list[dict]],
        file_counts: dict[str, int],
        dry_run: bool,
    ) -> tuple[list[UploadResult], dict[str, list[dict]], dict[str, int]]:
        """flush 达到阈值的桶，返回未 flush 的桶。"""
        results: list[UploadResult] = []
        remaining: dict[str, list[dict]] = defaultdict(list)
        remaining_counts: dict[str, int] = defaultdict(int)

        for right, rows in buckets.items():
            if len(rows) >= self.flush_threshold:
                result = self._flush_one(right, rows, file_counts[right], dry_run)
                results.append(result)
            else:
                remaining[right] = rows
                remaining_counts[right] = file_counts[right]

        return results, remaining, remaining_counts

    def _flush_all(
        self,
        buckets: dict[str, list[dict]],
        file_counts: dict[str, int],
        dry_run: bool,
    ) -> tuple[list[UploadResult], dict[str, list[dict]], dict[str, int]]:
        """flush 所有桶。"""
        results: list[UploadResult] = []
        for right, rows in buckets.items():
            if rows:
                result = self._flush_one(right, rows, file_counts[right], dry_run)
                results.append(result)
        return results, {}, defaultdict(int)

    def _flush_one(
        self, right: str, rows: list[dict], files_count: int, dry_run: bool
    ) -> UploadResult:
        """flush 一个桶的数据到 Supabase。"""
        self.console.print(
            f"  flush {right}: {files_count} 个文件, {len(rows)} 条记录"
        )

        if dry_run:
            return UploadResult(right, files_count, len(rows), True)

        upsert_fn = _UPSERT_MAP.get(right)
        if not upsert_fn:
            return UploadResult(
                right, files_count, 0, False, f"未知复权类型: {right}"
            )

        try:
            pages = (len(rows) + 999) // 1000

            def on_page(
                page: int, _batch: int, cum: int, *, _r=right, _p=pages
            ) -> None:
                self.console.print(f"    {_r} 第 {page}/{_p} 页 ({cum} 条)")

            count = upsert_fn(rows, on_page=on_page)
            self.console.print(f"[green]✓[/green] {right} 上传完成 ({count} 条)")
            return UploadResult(right, files_count, count, True)
        except Exception as e:
            self.console.print(f"[red]✗[/red] {right} 上传失败: {e}")
            return UploadResult(right, files_count, 0, False, str(e))

    def _read_file(
        self,
        file: Path,
        start_date: date | None,
        end_date: date | None,
    ) -> _FileData | _ReadError:
        """读取并解析单个 JSON 文件，按日期区间过滤记录。"""
        try:
            with open(file, encoding="utf-8") as f:
                raw = json.load(f)

            right = raw.get("right", "NR").upper()
            stock_code = raw.get("stock_code", "")
            records = raw.get("records", [])

            # 日期区间过滤
            if start_date:
                s = start_date.isoformat()
                records = [r for r in records if r["trade_date"] >= s]
            if end_date:
                e = end_date.isoformat()
                records = [r for r in records if r["trade_date"] <= e]

            rows = [
                {
                    "stock_code": stock_code,
                    "trade_date": rec["trade_date"],
                    "open": rec["open"],
                    "high": rec["high"],
                    "low": rec["low"],
                    "close": rec["close"],
                    "volume": rec["volume"],
                    "turnover": rec["turnover"],
                }
                for rec in records
            ]

            return _FileData(file, right, rows)

        except Exception as e:
            return _ReadError(file, str(e))
