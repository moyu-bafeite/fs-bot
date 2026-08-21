"""港交所股份回购报告（SRRPT）上传模块。

提供 JSON 文件读取、字段映射转换和并发上传到 Supabase 的能力。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lib.db import _md_client

TABLE_NAME = "hk_hkex_repurchase_reports"
MAX_WORKERS = 100

# JSON 字段 -> 表字段映射
FIELD_MAP = {
    "report_date": "report_date",
    "stock_code": "stock_code",
    "sec_type": "sec_type",
    "trade_date": "trade_date",
    "quantity": "quantity",
    "high_price": "high_price",
    "low_price": "low_price",
    "currency": "currency",
    "amount": "amount",
    "method": "method",
    "for_cancellation": "for_cancellation",
    "for_treasury": "for_treasury",
    "under_mandate": "cumulative_quantity",
    "pct_of_issued": "cumulative_pct",
}


def transform_record(record: dict) -> dict:
    """将 JSON 记录转换为表字段。"""
    row = {}
    for json_key, db_col in FIELD_MAP.items():
        row[db_col] = record.get(json_key)
    return row


def read_json_file(file: Path) -> list[dict]:
    """读取单个 JSON 文件，返回转换后的记录列表。"""
    with open(file, encoding="utf-8") as f:
        data = json.load(f)
    return [transform_record(r) for r in data]


def upload_file(file: Path, dry_run: bool = False) -> tuple[Path, int, str | None]:
    """处理单个文件，返回 (文件路径, 记录数, 错误信息或 None)。"""
    try:
        rows = read_json_file(file)
        if not rows:
            return file, 0, None

        if dry_run:
            return file, len(rows), None

        _md_client.table(TABLE_NAME).upsert(
            rows,
            on_conflict="report_date,stock_code,sec_type,trade_date,quantity,amount",
        ).execute()
        return file, len(rows), None
    except Exception as e:
        return file, 0, str(e)