#!/usr/bin/env python3
"""从 data/ 目录读取财报 JSON，增量写入 Supabase。

Pipeline:
  1. 扫描文件 → 与 manifest 对比 → 找出变更文件
  2. 按 ticker 分组 → 并行处理（ticker 级并行）
  3. 全局 field_defs 去重 → 批量写入
  4. 按 ticker 从磁盘重新计算 metadata → 批量写入
  5. 保存 manifest
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from lib.db import (
    insert_financial_items,
    upsert_field_defs_batch,
    upsert_us_fs_metadata,
)

console = Console()

MANIFEST_NAME = "_manifest.json"

MAX_FP_ORDER = {"Q1": 1, "H1": 2, "9M": 3, "ANNUAL": 4}
PERIOD_TO_MAX_FP = {
    "q1": "Q1",
    "q2": "H1",
    "h1": "H1",
    "q3": "9M",
    "9m": "9M",
    "q4": "ANNUAL",
    "annual": "ANNUAL",
    "quarterly_annual": "ANNUAL",
}
MAX_FP_TO_NAME = {v: k for k, v in MAX_FP_ORDER.items()}


# ── Manifest (per-ticker) ──


@dataclass
class Manifest:
    path: Path
    files: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, ticker_dir: Path) -> Manifest:
        path = ticker_dir / MANIFEST_NAME
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

    def diff(self, all_files: list[Path], ticker_dir: Path) -> list[Path]:
        """返回 mtime 或 size 发生变化的文件列表。"""
        changed: list[Path] = []
        for f in all_files:
            rel = str(f.relative_to(ticker_dir))
            stat = f.stat()
            entry = {"mtime": stat.st_mtime, "size": stat.st_size}
            if self.files.get(rel) != entry:
                changed.append(f)
        return changed

    def mark(self, file_path: Path, ticker_dir: Path) -> None:
        rel = str(file_path.relative_to(ticker_dir))
        stat = file_path.stat()
        self.files[rel] = {"mtime": stat.st_mtime, "size": stat.st_size}


# ── 数据结构 ──


@dataclass
class TickerPayload:
    ticker: str
    items: list[dict] = field(default_factory=list)
    field_defs: list[dict] = field(default_factory=list)
    processed_files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── 扫描 ──


def scan_all_files(data_dir: Path, tickers: set[str] | None = None) -> list[Path]:
    """递归扫描所有 [ticker]/[year]/[period].json 文件。"""
    if not data_dir.exists():
        return []
    files: list[Path] = []
    for ticker_dir in sorted(data_dir.iterdir()):
        if not ticker_dir.is_dir() or ticker_dir.name.startswith("_"):
            continue
        if tickers and ticker_dir.name not in tickers:
            continue
        for year_dir in ticker_dir.iterdir():
            if not year_dir.is_dir() or year_dir.name.startswith("_"):
                continue
            for f in year_dir.glob("*.json"):
                files.append(f)
    return files


def group_by_ticker(files: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        groups[f.parent.parent.name].append(f)
    return dict(groups)


# ── 单 ticker 处理 ──


def process_ticker(
    ticker: str,
    files: list[Path],
    data_dir: Path,
) -> TickerPayload:
    """读取该 ticker 的所有变更文件 → 批量写入 items → 收集 field_defs。"""
    payload = TickerPayload(ticker=ticker)

    # 读取并合并所有文件
    for file_path in files:
        try:
            data = json.loads(file_path.read_text())
            items = data.get("items", [])
            for row in items:
                row["ticker"] = ticker
            payload.items.extend(items)

            for key_str, dn in data.get("field_defs", {}).items():
                fid_str, st = key_str.split(":", 1)
                payload.field_defs.append(
                    {"field_id": int(fid_str), "statement": st, "display_name": dn}
                )
            payload.processed_files.append(file_path)
        except Exception as e:
            payload.errors.append(f"{file_path.relative_to(data_dir)}: {e}")

    # 批量 upsert items
    if payload.items:
        try:
            insert_financial_items(payload.items)
        except Exception as e:
            payload.errors.append(f"items upsert: {e}")
            payload.processed_files.clear()

    return payload


# ── metadata 计算 ──


def compute_metadata_from_disk(ticker_dir: Path) -> tuple[int, int, str]:
    """遍历 ticker 目录下所有 .json 文件，计算 min_fy / max_fy / max_fp。

    max_fp 取自最新财年内 period rank 最大的文件（annual > 9m > h1 > q1）。
    """
    min_fy, max_fy = 9999, 0
    latest_fy_max_rank = 0
    for year_dir in ticker_dir.iterdir():
        if not year_dir.is_dir() or year_dir.name.startswith("_"):
            continue
        try:
            fy = int(year_dir.name)
        except ValueError:
            continue
        min_fy = min(min_fy, fy)
        max_fy = max(max_fy, fy)

    # 找到最新财年，再在该财年内取 max period
    if max_fy > 0:
        latest_dir = ticker_dir / str(max_fy)
        if latest_dir.is_dir():
            for f in latest_dir.glob("*.json"):
                fp = f.stem
                period = PERIOD_TO_MAX_FP.get(fp, "ANNUAL")
                rank = MAX_FP_ORDER.get(period, 0)
                latest_fy_max_rank = max(latest_fy_max_rank, rank)

    if min_fy > max_fy:
        min_fy = max_fy = 0
    min_fy = max(min_fy, 2010)
    max_fp_name = MAX_FP_TO_NAME.get(latest_fy_max_rank, "ANNUAL")
    return min_fy, max_fy, max_fp_name


# ── field_defs 去重 ──


def deduplicate_field_defs(all_defs: list[dict]) -> list[dict]:
    """按 (field_id, statement) 去重，保留第一个出现的。"""
    seen: set[tuple[int, str]] = set()
    result: list[dict] = []
    for d in all_defs:
        key = (d["field_id"], d["statement"])
        if key not in seen:
            seen.add(key)
            result.append(d)
    return result


# ── 主流程 ──


def run(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    tickers_filter = None
    if args.tickers:
        tickers_filter = {t.strip() for t in args.tickers.split(",") if t.strip()}

    # Phase 1: Scan & Diff (per-ticker manifest)
    all_files = scan_all_files(data_dir, tickers_filter)
    if not all_files:
        console.print("  无数据文件")
        return

    all_ticker_files = group_by_ticker(all_files)
    # 每个 ticker 加载自己的 manifest 做 diff
    ticker_changed: dict[str, tuple[list[Path], Manifest]] = {}
    total_file_count = 0
    for ticker, files in all_ticker_files.items():
        ticker_dir = data_dir / ticker
        manifest = Manifest.load(ticker_dir)
        changed = manifest.diff(files, ticker_dir)
        if changed:
            ticker_changed[ticker] = (changed, manifest)
            total_file_count += len(changed)

    if not ticker_changed:
        console.print("  无变更文件")
        return

    console.print(
        f"  文件总数: {len(all_files):,}  变更: {total_file_count:,}  "
        f"涉及 ticker: {len(ticker_changed)}  并发: {args.workers}"
    )

    run_start = time.time()

    # Phase 2: Process tickers in parallel
    all_field_defs: list[dict] = []
    processed_tickers: set[str] = set()
    success_files = 0
    fail_files = 0
    total_rows = 0
    errors: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_ticker, ticker, files, data_dir): (ticker, manifest)
            for ticker, (files, manifest) in ticker_changed.items()
        }
        for future in as_completed(futures):
            ticker, manifest = futures[future]
            try:
                payload = future.result()
            except Exception as e:
                errors.append((ticker, f"线程异常: {e}"))
                continue

            if payload.errors:
                for err in payload.errors:
                    errors.append((ticker, err))

            if payload.processed_files:
                success_files += len(payload.processed_files)
                total_rows += len(payload.items)
                processed_tickers.add(ticker)
                all_field_defs.extend(payload.field_defs)
                ticker_dir = data_dir / ticker
                for f in payload.processed_files:
                    manifest.mark(f, ticker_dir)
                try:
                    manifest.save()
                except Exception as e:
                    errors.append((ticker, f"manifest 保存失败: {e}"))

            fail_files += len(payload.errors)

            if not args.quiet:
                status = (
                    "[green]OK[/green]"
                    if not payload.errors
                    else "[yellow]PARTIAL[/yellow]"
                )
                console.print(
                    f"  {ticker}: {len(payload.items):,} items, "
                    f"{len(payload.processed_files)} files {status}"
                )

    # Phase 3: Global field_defs upsert
    if all_field_defs:
        deduped = deduplicate_field_defs(all_field_defs)
        try:
            upsert_field_defs_batch(deduped)
            if not args.quiet:
                console.print(f"  field_defs: {len(deduped):,} 条")
        except Exception as e:
            errors.append(("*field_defs", str(e)))

    # Phase 4: Recompute metadata for processed tickers
    meta_ok = 0
    for ticker in sorted(processed_tickers):
        ticker_dir = data_dir / ticker
        try:
            min_fy, max_fy, max_fp = compute_metadata_from_disk(ticker_dir)
            upsert_us_fs_metadata(ticker, "USD", min_fy, max_fy, max_fp)
            meta_ok += 1
        except Exception as e:
            errors.append((ticker, f"metadata: {e}"))

    elapsed = time.time() - run_start

    # Summary
    summary = Table(title="推送完成", show_header=True, header_style="bold", box=None)
    summary.add_column("项目", style="bold")
    summary.add_column("值")
    summary.add_row("变更文件", f"{total_file_count:,}")
    summary.add_row("成功文件", f"{success_files:,}")
    summary.add_row("失败", f"{fail_files:,}")
    summary.add_row("写入行数", f"{total_rows:,}")
    summary.add_row("ticker 数", f"{len(processed_tickers):,}")
    summary.add_row("metadata", f"{meta_ok:,}")
    summary.add_row("耗时", f"{elapsed / 60:.1f} 分钟")
    if not args.quiet:
        console.print()
        console.print(summary)

    if errors and not args.quiet:
        err_table = Table(
            title="错误列表", show_header=True, header_style="bold red", box=None
        )
        err_table.add_column("Ticker", width=12)
        err_table.add_column("Error")
        for ticker, msg in sorted(set(errors)):
            err_table.add_row(ticker, msg[:80])
        console.print()
        console.print(err_table)

    if args.quiet:
        console.print(
            f"  推送完成: {success_files} ok, {fail_files} fail, "
            f"{total_rows} rows, {elapsed / 60:.1f}m"
        )

    # 日志
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"push_us_fs_{ts}.json"
    log_path.write_text(
        json.dumps(
            {
                "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "elapsed_seconds": round(elapsed, 1),
                "summary": {
                    "changed_files": total_file_count,
                    "success_files": success_files,
                    "fail_files": fail_files,
                    "rows_inserted": total_rows,
                    "tickers": len(processed_tickers),
                    "metadata": meta_ok,
                },
                "errors": [{"ticker": t, "error": m} for t, m in sorted(set(errors))],
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
    p = argparse.ArgumentParser(description="从 data/ 增量推送财报数据到 Supabase")
    p.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="逗号分隔的 ticker 列表 (默认扫描全部)",
    )
    p.add_argument(
        "--workers", type=int, default=5, help="并发线程数 (默认 5, 最大 20)"
    )
    p.add_argument("--data-dir", type=str, default="data", help="数据目录 (默认 data/)")
    p.add_argument("--quiet", action="store_true", help="cron 模式")
    args = p.parse_args()
    if args.workers < 1 or args.workers > 20:
        p.error("--workers 范围 1-20")
    return args


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
