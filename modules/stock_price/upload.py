"""股价数据上传器：将本地 JSON 文件上传到 Supabase。

两阶段设计：多线程并行读取文件，按复权类型分组后批量上传。
"""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from lib.db import upsert_br_daily_prices, upsert_nr_daily_prices

DEFAULT_INPUT_DIR = Path("downloads/stock_price")

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
    """股价数据上传器。

    用法::

        uploader = StockPriceUploader()
        results = uploader.upload(list(Path("downloads/stock_price").glob("*.json")))
    """

    console: Console = field(default_factory=Console)
    max_workers: int = 8

    def upload(
        self,
        files: list[Path],
        dry_run: bool = False,
    ) -> list[UploadResult]:
        """批量上传 JSON 文件到 Supabase。

        两阶段执行：
        1. 多线程并行读取并解析 JSON 文件
        2. 按复权类型分组，批量上传到 Supabase

        Args:
            files: JSON 文件路径列表
            dry_run: 仅打印，不实际上传
        """
        if not files:
            self.console.print("[yellow]无待上传文件[/yellow]")
            return []

        self.console.print(f"待上传 {len(files)} 个文件")
        if dry_run:
            self.console.print("[yellow]DRY RUN 模式[/yellow]")

        # 阶段1: 多线程并行读取
        file_data_list, read_errors = self._read_all(files)

        for err in read_errors:
            self.console.print(f"[red]✗ 读取失败[/red] {err.file.name}: {err.error}")

        if not file_data_list:
            self.console.print("[yellow]无有效数据[/yellow]")
            return []

        # 阶段2: 按复权类型分组，批量上传
        return self._upload_grouped(file_data_list, dry_run)

    def _read_all(
        self, files: list[Path]
    ) -> tuple[list[_FileData], list[_ReadError]]:
        """多线程并行读取并解析 JSON 文件。"""
        ok: list[_FileData] = []
        errors: list[_ReadError] = []

        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task_id = progress.add_task("读取文件", total=len(files))

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._read_file, file): file for file in files
                }
                for future in as_completed(futures):
                    result = future.result()
                    if isinstance(result, _FileData):
                        ok.append(result)
                    else:
                        errors.append(result)
                    progress.advance(task_id)

        return ok, errors

    def _upload_grouped(
        self,
        file_data_list: list[_FileData],
        dry_run: bool,
    ) -> list[UploadResult]:
        """按复权类型分组后批量上传。"""
        grouped: dict[str, list[dict]] = defaultdict(list)
        file_counts: dict[str, int] = defaultdict(int)

        for fd in file_data_list:
            grouped[fd.right].extend(fd.rows)
            file_counts[fd.right] += 1

        results: list[UploadResult] = []

        for right, rows in grouped.items():
            files_count = file_counts[right]
            self.console.print(
                f"  {right}: {files_count} 个文件, {len(rows)} 条记录"
            )

            if dry_run:
                results.append(UploadResult(right, files_count, len(rows), True))
                continue

            upsert_fn = _UPSERT_MAP.get(right)
            if not upsert_fn:
                results.append(
                    UploadResult(right, files_count, 0, False, f"未知复权类型: {right}")
                )
                continue

            try:
                pages = (len(rows) + 999) // 1000

                def on_page(
                    page: int, _batch: int, cum: int, *, _r=right, _p=pages
                ) -> None:
                    self.console.print(f"    第 {page}/{_p} 页 ({cum} 条)")

                count = upsert_fn(rows, on_page=on_page)
                results.append(UploadResult(right, files_count, count, True))
                self.console.print(f"[green]✓[/green] {right} 上传完成 ({count} 条)")
            except Exception as e:
                results.append(UploadResult(right, files_count, 0, False, str(e)))
                self.console.print(f"[red]✗[/red] {right} 上传失败: {e}")

        total = sum(r.records_count for r in results if r.success)
        fail = sum(1 for r in results if not r.success)
        self.console.print(f"\n完成: {total} 条记录, {fail} 组失败")

        return results

    def _read_file(self, file: Path) -> _FileData | _ReadError:
        """读取并解析单个 JSON 文件。"""
        try:
            with open(file, encoding="utf-8") as f:
                raw = json.load(f)

            right = raw.get("right", "NR").upper()
            stock_code = raw.get("stock_code", "")
            records = raw.get("records", [])

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
