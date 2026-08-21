"""港交所股份回购报告（SRRPT）上传 CLI 入口。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console

from modules.upload_hkex_srrpt import MAX_WORKERS, upload_file

DEFAULT_INPUT_DIR = Path("output/srrpt")


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
        futures = {executor.submit(upload_file, f, args.dry_run): f for f in files}
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
