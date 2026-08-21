"""港交所股份回购报告（SRRPT）上传 CLI 入口。"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pyrate_limiter import Duration, Limiter, Rate
from rich.console import Console

from modules.hkex_srrpt.upload_hkex_srrpt import MAX_WORKERS, upload_file

# 限流配置: 每秒最多 10 个请求
_RATE = Rate(10, Duration.SECOND)
_limiter = Limiter(_RATE)

DEFAULT_INPUT_DIR = Path("output/srrpt")
MANIFEST_NAME = "_manifest.json"


def _load_manifest(manifest_path: Path) -> dict[str, int]:
    """读取 manifest，返回 {文件名: 记录数}。"""
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_manifest(manifest_path: Path, manifest: dict[str, int]) -> None:
    """保存 manifest。"""
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


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
        manifest_path = args.file.parent / MANIFEST_NAME
    else:
        files = sorted(f for f in args.input_dir.glob("*.json") if f.name != MANIFEST_NAME)
        manifest_path = args.input_dir / MANIFEST_NAME

    if not files:
        console.print(f"[yellow]未找到 JSON 文件: {args.input_dir}[/yellow]")
        return

    # 读取 manifest，跳过已上传的文件
    manifest = _load_manifest(manifest_path)
    skipped = [f for f in files if f.name in manifest]
    pending = [f for f in files if f.name not in manifest]

    if skipped:
        console.print(f"跳过 {len(skipped)} 个已上传文件")

    if not pending:
        console.print("[yellow]所有文件均已上传[/yellow]")
        return

    console.print(f"待上传 {len(pending)} 个文件")
    if args.dry_run:
        console.print("[yellow]DRY RUN 模式[/yellow]")

    total_rows = 0
    failed: list[tuple[Path, str]] = []
    succeeded: dict[str, int] = {}

    def _rate_limited_upload(file: Path, dry_run: bool) -> tuple[Path, int, str | None]:
        _limiter.try_acquire("upload", blocking=True)
        return upload_file(file, dry_run)

    with ThreadPoolExecutor(max_workers=min(args.workers, MAX_WORKERS)) as executor:
        futures = {executor.submit(_rate_limited_upload, f, args.dry_run): f for f in pending}
        for future in as_completed(futures):
            file, count, error = future.result()
            if error:
                failed.append((file, error))
                console.print(f"[red]✗[/red] {file.name}: {error}")
            else:
                total_rows += count
                succeeded[file.name] = count
                console.print(f"[green]✓[/green] {file.name} ({count} 条)")

    # 更新 manifest
    if succeeded and not args.dry_run:
        manifest.update(succeeded)
        _save_manifest(manifest_path, manifest)

    console.print(f"\n完成: {total_rows} 条记录, {len(failed)} 个文件失败")
    if failed:
        console.print("[red]失败文件:[/red]")
        for f, err in failed:
            console.print(f"  {f.name}: {err}")
