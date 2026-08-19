#!/usr/bin/env python3
"""从 data/repurchase_actions/ 目录读取回购 JSON，增量写入 Supabase。

Pipeline:
  1. 扫描文件 → 与 manifest 对比 → 找出变更文件
  2. 多线程读取变更文件 → 写入数据库
  3. 保存 manifest
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from lib.db import upsert_hk_repurchase_actions

console = Console()

MANIFEST_NAME = "_manifest.json"


@dataclass
class Manifest:
    path: Path
    files: dict[str, dict] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def load(cls, data_dir: Path) -> Manifest:
        path = data_dir / MANIFEST_NAME
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return cls(path=path, files=data.get("files", {}))
            except (json.JSONDecodeError, KeyError):
                pass
        return cls(path=path)

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {"version": 1, "files": self.files},
                ensure_ascii=False,
                indent=2,
            )
        )

    def diff(self, all_files: list[Path]) -> list[Path]:
        """返回 mtime 或 size 发生变化的文件列表。"""
        changed: list[Path] = []
        for f in all_files:
            rel = f.name
            stat = f.stat()
            entry = {"mtime": stat.st_mtime, "size": stat.st_size}
            if self.files.get(rel) != entry:
                changed.append(f)
        return changed

    def mark(self, file_path: Path) -> None:
        rel = file_path.name
        stat = file_path.stat()
        with self._lock:
            self.files[rel] = {"mtime": stat.st_mtime, "size": stat.st_size}


@dataclass
class PushResult:
    stock_code: str
    record_count: int = 0
    error_msg: str = ""


def scan_files(data_dir: Path, stock_codes: set[str] | None = None) -> list[Path]:
    """扫描 repurchase_actions 目录下的所有 .json 文件。"""
    if not data_dir.exists():
        return []
    files: list[Path] = []
    for f in sorted(data_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        code = f.stem
        if stock_codes and code not in stock_codes:
            continue
        files.append(f)
    return files


def _process_one_file(file_path: Path) -> PushResult:
    """处理单个文件：读取并写入数据库。"""
    stock_code = file_path.stem
    try:
        records = json.loads(file_path.read_text())
        if not isinstance(records, list):
            raise ValueError(f"文件格式错误: 期望数组，得到 {type(records)}")
        if records:
            upsert_hk_repurchase_actions(records)
        return PushResult(stock_code=stock_code, record_count=len(records))
    except Exception as e:
        return PushResult(stock_code=stock_code, error_msg=str(e))


def push_files(
    files: list[Path],
    quiet: bool,
    workers: int = 4,
) -> tuple[int, list[PushResult]]:
    """多线程读取文件并写入数据库。"""
    results: list[PushResult] = []
    total_records = 0
    completed = 0
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_process_one_file, f): f for f in files}

        for future in as_completed(futures):
            result = future.result()
            with lock:
                results.append(result)
                if not result.error_msg:
                    total_records += result.record_count
                completed += 1
                if not quiet:
                    status = "OK" if not result.error_msg else "FAIL"
                    console.print(
                        f"  [{completed:>4d}/{len(files)}] {result.stock_code} - "
                        f"{result.record_count} records [{status}]"
                    )

    return total_records, results


def run(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    stock_codes_filter = None
    if args.stock_codes:
        stock_codes_filter = {
            c.strip() for c in args.stock_codes.split(",") if c.strip()
        }

    # Phase 1: Scan & Diff
    all_files = scan_files(data_dir, stock_codes_filter)
    if not all_files:
        console.print("  无数据文件")
        return

    manifest = Manifest.load(data_dir)
    changed = manifest.diff(all_files)

    if not changed:
        console.print("  无变更文件")
        return

    if not args.quiet:
        console.print(f"  文件总数: {len(all_files)}  变更: {len(changed)}")

    # Phase 2: Push
    start_time = time.time()
    total_records, results = push_files(changed, args.quiet, args.workers)
    elapsed = time.time() - start_time

    # Phase 3: Mark & Save manifest
    success_results = [r for r in results if not r.error_msg]
    fail_results = [r for r in results if r.error_msg]

    for r in success_results:
        file_path = data_dir / f"{r.stock_code}.json"
        if file_path.exists():
            manifest.mark(file_path)
    manifest.save()

    # Summary
    if not args.quiet:
        summary = Table(
            title="推送完成", show_header=True, header_style="bold", box=None
        )
        summary.add_column("项目", style="bold")
        summary.add_column("值")
        summary.add_row("变更文件", f"{len(changed):,}")
        summary.add_row("成功", f"{len(success_results):,}")
        summary.add_row("失败", f"{len(fail_results):,}")
        summary.add_row("总记录", f"{total_records:,}")
        summary.add_row("耗时", f"{elapsed:.1f} 秒")
        console.print()
        console.print(summary)

        if fail_results:
            err_table = Table(
                title="失败列表", show_header=True, header_style="bold red", box=None
            )
            err_table.add_column("Stock Code", width=12)
            err_table.add_column("Error")
            for r in sorted(fail_results, key=lambda r: r.stock_code):
                err_table.add_row(r.stock_code, r.error_msg[:80])
            console.print()
            console.print(err_table)
    else:
        console.print(
            f"  推送完成: {len(success_results)} ok, {len(fail_results)} fail, "
            f"{total_records} records, {elapsed:.1f}s"
        )

    # 日志
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"push_hk_repurchase_{ts}.json"
    log_path.write_text(
        json.dumps(
            {
                "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "elapsed_seconds": round(elapsed, 1),
                "summary": {
                    "changed_files": len(changed),
                    "success": len(success_results),
                    "fail": len(fail_results),
                    "total_records": total_records,
                },
                "fail_list": [
                    {"stock_code": r.stock_code, "error": r.error_msg}
                    for r in sorted(fail_results, key=lambda r: r.stock_code)
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not args.quiet:
        console.print(f"\n  日志已写入: {log_path}")
    else:
        console.print(f"  日志: {log_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="从 data/repurchase_actions/ 推送回购数据到 Supabase"
    )
    p.add_argument(
        "--stock-codes",
        type=str,
        default=None,
        help="逗号分隔的 stock_code 列表 (默认扫描全部)",
    )
    p.add_argument(
        "--data-dir", type=str, default="data/repurchase_actions", help="数据目录"
    )
    p.add_argument("--workers", type=int, default=4, help="并发线程数 (默认 4)")
    p.add_argument("--quiet", action="store_true", help="cron 模式")
    args = p.parse_args()
    return args


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
