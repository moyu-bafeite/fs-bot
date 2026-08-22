"""股价数据上传器：将本地 JSON 文件上传到 Supabase。

支持 manifest 追踪已上传文件，避免重复上传。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pyrate_limiter import Duration, Limiter, Rate
from rich.console import Console

from lib.db import upsert_br_daily_prices, upsert_nr_daily_prices
from lib.manifest import MANIFEST_NAME, Manifest

DEFAULT_INPUT_DIR = Path("downloads/stock_price")

# 限流: 每秒最多 10 个请求
_RATE = Rate(10, Duration.SECOND)
_limiter = Limiter(_RATE)

# right -> upsert 函数映射
_UPSERT_MAP = {
    "BR": upsert_br_daily_prices,
    "NR": upsert_nr_daily_prices,
}


@dataclass(frozen=True)
class UploadResult:
    """单个文件的上传结果。"""

    file: Path
    right: str
    records_count: int
    success: bool
    error: str = ""


@dataclass
class StockPriceUploader:
    """股价数据上传器。

    用法::

        uploader = StockPriceUploader()
        results = uploader.upload(list(Path("downloads/stock_price").glob("*.json")))
    """

    console: Console = field(default_factory=Console)

    def upload(
        self,
        files: list[Path],
        dry_run: bool = False,
    ) -> list[UploadResult]:
        """批量上传 JSON 文件到 Supabase。

        Args:
            files: JSON 文件路径列表
            dry_run: 仅打印，不实际上传
        """
        if not files:
            self.console.print("[yellow]无待上传文件[/yellow]")
            return []

        # 读取 manifest，跳过已上传
        manifest = Manifest(files[0].parent / MANIFEST_NAME)

        pending = [f for f in files if not manifest.contains(f.name)]
        skipped = [f for f in files if manifest.contains(f.name)]

        if skipped:
            self.console.print(f"跳过 {len(skipped)} 个已上传文件")

        if not pending:
            self.console.print("[yellow]所有文件均已上传[/yellow]")
            return []

        self.console.print(f"待上传 {len(pending)} 个文件")
        if dry_run:
            self.console.print("[yellow]DRY RUN 模式[/yellow]")

        results: list[UploadResult] = []
        succeeded: dict[str, int] = {}

        for file in pending:
            result = self._upload_one(file, dry_run)
            results.append(result)
            if result.success:
                succeeded[file.name] = result.records_count
                self.console.print(
                    f"[green]✓[/green] {file.name} ({result.records_count} 条)"
                )
            else:
                self.console.print(f"[red]✗[/red] {file.name}: {result.error}")

        # 更新 manifest
        if succeeded and not dry_run:
            manifest.update(succeeded)
            manifest.save()

        total = sum(r.records_count for r in results if r.success)
        fail = sum(1 for r in results if not r.success)
        self.console.print(f"\n完成: {total} 条记录, {fail} 个文件失败")

        return results

    def _upload_one(self, file: Path, dry_run: bool) -> UploadResult:
        """上传单个文件。"""
        try:
            with open(file, encoding="utf-8") as f:
                data = json.load(f)

            stock_code = data.get("stock_code", "")
            right = data.get("right", "NR").upper()
            records = data.get("records", [])

            if not records:
                return UploadResult(file, right, 0, True)

            # 构建数据库记录
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

            if dry_run:
                return UploadResult(file, right, len(rows), True)

            _limiter.try_acquire("upload", blocking=True)

            upsert_fn = _UPSERT_MAP.get(right)
            if not upsert_fn:
                return UploadResult(file, right, 0, False, f"未知复权类型: {right}")

            count = upsert_fn(rows)
            return UploadResult(file, right, count, True)

        except Exception as e:
            return UploadResult(file, "", 0, False, str(e))
