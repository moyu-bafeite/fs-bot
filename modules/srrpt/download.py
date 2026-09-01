"""港交所股份回购报告（SRRPT）批量下载器。

多线程并行下载指定日期区间内的 SRRPT .xls 文件，
内置限流控制避免触发 HKEX 反爬机制。

URL 格式: https://www3.hkexnews.hk/reports/sharerepur/documents/SRRPTYYYYMMDD.xls
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
from pyrate_limiter import Duration, Limiter, Rate
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

# ── 常量 ──

_BASE_URL = "https://www3.hkexnews.hk/reports/sharerepur/documents"
_DEFAULT_DIR = Path("downloads/srrpt")

# 限流配置: 每秒最多 5 个请求
_RATE = Rate(5, Duration.SECOND)

# HTTP 超时（秒）
_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 30


# ── 数据模型 ──


@dataclass(frozen=True)
class DownloadResult:
    """单个文件的下载结果。"""

    target_date: date
    url: str
    path: Path | None
    success: bool
    error: str = ""


# ── 下载器 ──


class HKEXSrrptDownloader:
    """港交所股份回购报告批量下载器。

    用法::

        dl = HKEXSrrptDownloader()
        results = dl.download_range(date(2026, 8, 1), date(2026, 8, 20))

        # 自定义目录和并发数
        dl = HKEXSrrptDownloader(output_dir=Path("data/srrpt"), workers=3)
        results = dl.download_dates([date(2026, 8, 10), date(2026, 8, 15)])
    """

    def __init__(
        self,
        output_dir: Path | str = _DEFAULT_DIR,
        workers: int = 5,
        skip_existing: bool = True,
        console: Console | None = None,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._workers = min(workers, _RATE.limit)  # 并发数不超过限流速率
        self._skip_existing = skip_existing
        self._console = console or Console()
        self._limiter = Limiter(_RATE)

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    # ── 公开方法 ──

    def download_range(self, start: date, end: date) -> list[DownloadResult]:
        """下载 start 到 end（含两端）之间每个交易日的报告。

        仅生成工作日（周一至周五），周末自动跳过。
        """
        dates = self._generate_dates(start, end)
        return self.download_dates(dates)

    def download_dates(self, dates: list[date]) -> list[DownloadResult]:
        """下载指定日期列表的报告。"""
        if not dates:
            return []

        self._output_dir.mkdir(parents=True, exist_ok=True)
        tasks = [(d, self._build_url(d), self._build_path(d)) for d in dates]

        # 过滤已存在的文件
        pending: list[tuple[date, str, Path]] = []
        skipped: list[DownloadResult] = []
        for d, url, path in tasks:
            if self._skip_existing and path.exists():
                skipped.append(DownloadResult(d, url, path, True))
            else:
                pending.append((d, url, path))

        if skipped:
            self._console.print(f"[yellow]WARNING: 跳过 {len(skipped)} 个已存在的文件[/yellow]")

        if not pending:
            return skipped

        self._console.print(
            f"开始下载 {len(pending)} 个文件（{self._workers} 线程）..."
        )

        results = self._download_batch(pending)
        return skipped + results

    # ── 内部方法 ──

    @staticmethod
    def _build_url(d: date) -> str:
        return f"{_BASE_URL}/SRRPT{d.strftime('%Y%m%d')}.xls"

    def _build_path(self, d: date) -> Path:
        return self._output_dir / f"SRRPT{d.strftime('%Y%m%d')}.xls"

    @staticmethod
    def _generate_dates(start: date, end: date) -> list[date]:
        """生成日期列表，仅包含工作日。"""
        dates: list[date] = []
        current = start
        while current <= end:
            if current.weekday() < 5:  # 周一至周五
                dates.append(current)
            current += timedelta(days=1)
        return dates

    def _download_batch(
        self, tasks: list[tuple[date, str, Path]]
    ) -> list[DownloadResult]:
        """多线程下载一批文件。"""
        results: list[DownloadResult] = []

        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self._console,
        ) as progress:
            task_id = progress.add_task("下载中", total=len(tasks))

            with ThreadPoolExecutor(max_workers=self._workers) as pool:
                futures = {
                    pool.submit(self._download_one, d, url, path): (d, url, path)
                    for d, url, path in tasks
                }

                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    progress.advance(task_id)

        # 统计
        ok = sum(1 for r in results if r.success)
        fail = len(results) - ok
        self._console.print(f"完成: {ok} 成功, {fail} 失败")

        return results

    def _download_one(self, d: date, url: str, path: Path) -> DownloadResult:
        """下载单个文件（带限流）。"""
        self._limiter.try_acquire(f"srrpt_{d}", blocking=True)

        try:
            with httpx.Client(
                timeout=httpx.Timeout(_CONNECT_TIMEOUT, read=_READ_TIMEOUT),
                follow_redirects=True,
            ) as client:
                resp = client.get(url)

                if resp.status_code == 404:
                    return DownloadResult(d, url, None, False, "文件不存在（非交易日）")

                resp.raise_for_status()
                path.write_bytes(resp.content)
                return DownloadResult(d, url, path, True)

        except httpx.HTTPStatusError as e:
            return DownloadResult(d, url, None, False, f"HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            return DownloadResult(d, url, None, False, f"请求失败: {e}")
        except Exception as e:
            return DownloadResult(d, url, None, False, f"未知错误: {e}")
