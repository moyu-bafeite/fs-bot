"""港交所股份回购报告（SRRPT）上传 CLI 入口。"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console

from lib.db import _md_client

DEFAULT_INPUT_DIR = Path("output/srrpt")
MAX_WORKERS = 100
TABLE_NAME = "hk_hkex_repurchase_reports"

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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="上传港交所股份回购报告到 Supabase")
    p.add_argument("--file", type=Path, default=None, help="指定单个 JSON 文件，优先于 --input-dir")
    p.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="JSON 文件目录（默认 output/srrpt），--file 优先",
    )
    p.add_argument("--workers", type=int, default=MAX_WORKERS, help="并发线程数")
    p.add_argument("--dry-run", action="store_true", help="仅打印，不实际插入")
    return p.parse_args()


def _transform_record(record: dict) -> dict:
    """将 JSON 记录转换为表字段。"""
    row = {}
    for json_key, db_col in FIELD_MAP.items():
        row[db_col] = record.get(json_key)
    return row


def _read_json_file(file: Path) -> list[dict]:
    """读取单个 JSON 文件，返回转换后的记录列表。"""
    with open(file, encoding="utf-8") as f:
        data = json.load(f)
    return [_transform_record(r) for r in data]


def _upload_file(file: Path, dry_run: bool) -> tuple[Path, int, str | None]:
    """处理单个文件，返回 (文件路径, 记录数, 错误信息或 None)。"""
    try:
        rows = _read_json_file(file)
        if not rows:
            return file, 0, None

        if dry_run:
            return file, len(rows), None

        _md_client.table(TABLE_NAME).insert(rows).execute()
        return file, len(rows), None
    except Exception as e:
        return file, 0, str(e)


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()

    console = Console()

    if args.file:
        files = [args.file]
    else:
        files = sorted(args.input_dir.glob("*.json"))

    if not files:
        console.print(f"[yellow]未找到 JSON 文件: {args.input_dir}[/yellow]")
        return

    console.print(f"共 {len(files)} 个文件")
    if args.dry_run:
        console.print("[yellow]DRY RUN 模式[/yellow]")

    total_rows = 0
    failed: list[tuple[Path, str]] = []

    with ThreadPoolExecutor(max_workers=min(args.workers, MAX_WORKERS)) as executor:
        futures = {executor.submit(_upload_file, f, args.dry_run): f for f in files}
        for future in as_completed(futures):
            file, count, error = future.result()
            if error:
                failed.append((file, error))
                console.print(f"[red]✗[/red] {file.name}: {error}")
            else:
                total_rows += count
                console.print(f"[green]✓[/green] {file.name} ({count} 条)")

    console.print(f"\n完成: {total_rows} 条记录, {len(failed)} 个文件失败")
    if failed:
        console.print("[red]失败文件:[/red]")
        for f, err in failed:
            console.print(f"  {f.name}: {err}")
