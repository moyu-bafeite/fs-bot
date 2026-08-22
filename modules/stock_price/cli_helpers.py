"""股价数据下载 CLI 包装层。

调用 modules.stock_price.download 执行实际下载，
本层只负责参数解析、数据库标的解析、Rich 进度展示。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from tigeropen.common.consts import QuoteRight

from lib.db import get_hk_stocks
from modules.stock_price.download import DownloadResult, download_one
from modules.stock_price.tiger_kline import TigerKlineFetcher

_DEFAULT_DIR = Path("downloads/stock_price")


@dataclass
class StockPriceDownloader:
    """股价数据下载器（CLI 包装）。

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
            rights: 复权方式列表 [QuoteRight.NR], [QuoteRight.BR], 或两者
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

        # 构建任务列表: (stock_code, right_label, right_enum)
        tasks: list[tuple[str, str, QuoteRight]] = []
        for ticker in tickers:
            for right in rights:
                label = right.value.upper()  # "NR" or "BR"
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
                result = download_one(
                    self.fetcher,
                    self.output_dir,
                    ticker,
                    label,
                    right,
                    start_date,
                    end_date,
                )
                results.append(result)
                progress.advance(task_id)

        ok = sum(1 for r in results if r.success)
        skip = sum(1 for r in results if r.success and r.records_count == 0)
        fail = len(results) - ok
        self.console.print(f"完成: {ok - skip} 新增, {skip} 跳过, {fail} 失败")

        return results
