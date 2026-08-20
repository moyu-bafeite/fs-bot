"""港交所股份回购报告（SRRPT）解析器 CLI 入口。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console

from modules.parse_hkex_srrpt import HKEXSrrptParser

DEFAULT_INPUT_DIR = Path("downloads/srrpt")
DEFAULT_OUTPUT_DIR = Path("output/srrpt")
MAX_WORKERS = 100


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="解析港交所股份回购报告（SRRPT）")
    p.add_argument("file", nargs="?", type=Path, default=None, help=".xls 文件路径")
    p.add_argument("--json", action="store_true", help="输出 JSON 格式")
    p.add_argument("--csv", action="store_true", help="输出 CSV 格式")
    p.add_argument("--output", "-o", type=Path, default=None, help="输出文件路径")
    p.add_argument("--workers", type=int, default=MAX_WORKERS, help="并发线程数")
    return p.parse_args()


def _process_single(file: Path, output_dir: Path, fmt: str) -> tuple[Path, str | None]:
    """处理单个文件，返回 (文件路径, 错误信息或 None)。"""
    try:
        parser = HKEXSrrptParser(file)
        parser.load()

        stem = file.stem
        if fmt == "json":
            parser.save_json(output_dir / f"{stem}.json")
        else:
            parser.save_csv(output_dir / f"{stem}.csv")
        return file, None
    except Exception as e:
        return file, str(e)


def _batch_process(input_dir: Path, output_dir: Path, fmt: str, workers: int) -> None:
    """批量处理目录下所有 .xls 文件。"""
    console = Console()
    files = sorted(input_dir.glob("*.xls"))

    if not files:
        console.print(f"[yellow]未找到 .xls 文件: {input_dir}[/yellow]")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"共 {len(files)} 个文件，输出目录: {output_dir}")

    failed: list[tuple[Path, str]] = []
    with ThreadPoolExecutor(max_workers=min(workers, MAX_WORKERS)) as executor:
        futures = {
            executor.submit(_process_single, f, output_dir, fmt): f for f in files
        }
        for future in as_completed(futures):
            file, error = future.result()
            if error:
                failed.append((file, error))
                console.print(f"[red]✗[/red] {file.name}: {error}")
            else:
                console.print(f"[green]✓[/green] {file.name}")

    console.print(f"\n完成: {len(files) - len(failed)} 成功, {len(failed)} 失败")
    if failed:
        console.print("[red]失败文件:[/red]")
        for f, err in failed:
            console.print(f"  {f.name}: {err}")


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()

    console = Console()
    fmt = "json" if args.json else "csv"

    if args.file is None:
        _batch_process(
            DEFAULT_INPUT_DIR, args.output or DEFAULT_OUTPUT_DIR, fmt, args.workers
        )
        return

    parser = HKEXSrrptParser(args.file)
    parser.load()

    if args.json:
        if args.output:
            parser.save_json(args.output)
            console.print(f"[green]已保存 JSON 到 {args.output}[/green]")
        else:
            print(parser.to_json())
    elif args.csv:
        if args.output:
            parser.save_csv(args.output)
            console.print(f"[green]已保存 CSV 到 {args.output}[/green]")
        else:
            print(parser.to_csv())
    else:
        parser.print(console)
