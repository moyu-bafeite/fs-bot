"""股价数据下载与增量合并。

从 Tiger API 获取日K线数据，支持检测已有文件的最大日期并只拉取增量部分。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tigeropen.common.consts import QuoteRight

from modules.stock_price.tiger_kline import TigerKlineFetcher


@dataclass(frozen=True)
class DownloadResult:
    """单个文件的下载结果。"""

    stock_code: str
    right: str
    path: Path | None
    records_count: int
    success: bool
    error: str = ""


def download_one(
    fetcher: TigerKlineFetcher,
    output_dir: Path,
    stock_code: str,
    right_label: str,
    right: QuoteRight,
    start_date: date,
    end_date: date,
) -> DownloadResult:
    """下载单个标的的一种复权数据，支持增量合并。

    检测 output_dir 下是否已有同名 JSON 文件，若有则读取其中最大日期，
    只从 Tiger API 拉取新增部分，合并去重后写回文件。
    """
    file_path = output_dir / f"{stock_code}_{right_label}.json"

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
        new_records = fetcher.fetch_daily(stock_code, effective_start, end_date, right)
    except Exception as e:
        return DownloadResult(stock_code, right_label, None, 0, False, str(e))

    merged = _merge_records(existing_records, new_records)

    output = {
        "stock_code": stock_code,
        "right": right_label,
        "records": merged,
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return DownloadResult(stock_code, right_label, file_path, len(new_records), True)


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
