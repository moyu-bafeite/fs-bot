"""港交所回购报告 ETL CLI。

子命令:
  download - 批量下载 SRRPT .xls 文件
  parse    - 解析 .xls 为 JSON/CSV
  upload   - 上传 JSON 到 Supabase
"""

from __future__ import annotations

import argparse
from datetime import date


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def register(subparsers) -> None:
    p = subparsers.add_parser("srrpt", help="港交所回购报告 ETL")
    sub = p.add_subparsers(dest="srrpt_command")

    dl = sub.add_parser("download", help="批量下载 SRRPT .xls 文件")
    dl.add_argument("--start", required=True, type=_parse_date, help="起始日期")
    dl.add_argument("--end", required=True, type=_parse_date, help="结束日期")
    dl.add_argument("--output-dir", default=None, help="输出目录")
    dl.add_argument("--workers", type=int, default=5, help="并发线程数")
    dl.add_argument("--no-skip", action="store_true", help="不跳过已存在的文件")

    ps = sub.add_parser("parse", help="解析 .xls 为 JSON/CSV")
    ps.add_argument("file", nargs="?", type=str, default=None, help=".xls 文件路径")
    ps.add_argument("--json", action="store_true", help="输出 JSON 格式")
    ps.add_argument("--csv", action="store_true", help="输出 CSV 格式")
    ps.add_argument("--output", "-o", type=str, default=None, help="输出文件路径")
    ps.add_argument("--workers", type=int, default=100, help="并发线程数")

    up = sub.add_parser("upload", help="上传 JSON 到 Supabase")
    up.add_argument("--file", type=str, default=None, help="指定单个 JSON 文件")
    up.add_argument("--input-dir", type=str, default=None, help="JSON 文件目录")
    up.add_argument("--workers", type=int, default=100, help="并发线程数")
    up.add_argument("--dry-run", action="store_true", help="仅打印，不实际插入")

    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    cmd = getattr(args, "srrpt_command", None)
    if cmd == "download":
        _run_download(args)
    elif cmd == "parse":
        _run_parse(args)
    elif cmd == "upload":
        _run_upload(args)
    else:
        import sys

        sys.argv = ["srrpt", "--help"]
        # Re-parse to show help
        p = argparse.ArgumentParser(description="港交所回购报告 ETL")
        sub = p.add_subparsers(dest="cmd")
        sub.add_parser("download")
        sub.add_parser("parse")
        sub.add_parser("upload")
        p.parse_args(["--help"])


def _run_download(args: argparse.Namespace) -> None:
    from rich.console import Console
    from modules.srrpt.download import HKEXSrrptDownloader

    console = Console()
    kwargs: dict = {
        "console": console,
        "workers": args.workers,
        "skip_existing": not args.no_skip,
    }
    if args.output_dir is not None:
        kwargs["output_dir"] = args.output_dir

    dl = HKEXSrrptDownloader(**kwargs)
    results = dl.download_range(args.start, args.end)

    failed = [r for r in results if not r.success]
    if failed:
        console.print(f"\n[red]{len(failed)} 个文件下载失败:[/red]")
        for r in failed:
            console.print(f"  {r.target_date}: {r.error}")


def _run_parse(args: argparse.Namespace) -> None:
    from pathlib import Path
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from rich.console import Console
    from modules.srrpt.parse import HKEXSrrptParser

    console = Console()
    fmt = "json" if args.json else "csv"

    if args.file is None:
        input_dir = Path("downloads/srrpt")
        output_dir = Path(args.output) if args.output else Path("output/srrpt")
        files = sorted(input_dir.glob("*.xls"))
        if not files:
            console.print(f"[yellow]未找到 .xls 文件: {input_dir}[/yellow]")
            return
        output_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"共 {len(files)} 个文件，输出目录: {output_dir}")

        max_workers = min(args.workers, 100)
        failed_list: list[tuple[Path, str]] = []

        def _process(file: Path):
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

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_process, f): f for f in files}
            for future in as_completed(futures):
                file, error = future.result()
                if error:
                    failed_list.append((file, error))
                    console.print(f"[red]✗[/red] {file.name}: {error}")
                else:
                    console.print(f"[green]✓[/green] {file.name}")

        console.print(
            f"\n完成: {len(files) - len(failed_list)} 成功, {len(failed_list)} 失败"
        )
        if failed_list:
            console.print("[red]失败文件:[/red]")
            for f, err in failed_list:
                console.print(f"  {f.name}: {err}")
        return

    file = Path(args.file)
    parser = HKEXSrrptParser(file)
    parser.load()

    output = Path(args.output) if args.output else None
    if args.json:
        if output:
            parser.save_json(output)
            console.print(f"[green]已保存 JSON 到 {output}[/green]")
        else:
            print(parser.to_json())
    elif args.csv:
        if output:
            parser.save_csv(output)
            console.print(f"[green]已保存 CSV 到 {output}[/green]")
        else:
            print(parser.to_csv())
    else:
        parser.print(console)


def _run_upload(args: argparse.Namespace) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pathlib import Path
    from pyrate_limiter import Duration, Limiter, Rate
    from rich.console import Console
    from lib.manifest import MANIFEST_NAME, Manifest
    from modules.srrpt.upload import upload_file

    rate = Rate(10, Duration.SECOND)
    limiter = Limiter(rate)
    console = Console()

    if args.file:
        files = [Path(args.file)]
        manifest_path = files[0].parent / MANIFEST_NAME
    else:
        input_dir = Path(args.input_dir) if args.input_dir else Path("output/srrpt")
        files = sorted(f for f in input_dir.glob("*.json") if f.name != MANIFEST_NAME)
        manifest_path = input_dir / MANIFEST_NAME

    if not files:
        console.print("[yellow]未找到 JSON 文件[/yellow]")
        return

    manifest = Manifest(manifest_path)
    pending = [f for f in files if not manifest.contains(f.name)]
    skipped = [f for f in files if manifest.contains(f.name)]

    if skipped:
        console.print(f"跳过 {len(skipped)} 个已上传文件")
    if not pending:
        console.print("[yellow]所有文件均已上传[/yellow]")
        return

    console.print(f"待上传 {len(pending)} 个文件")
    if args.dry_run:
        console.print("[yellow]DRY RUN 模式[/yellow]")

    total_rows = 0
    failed_list: list[tuple[Path, str]] = []
    succeeded: dict[str, int] = {}

    def _rate_limited_upload(file: Path, dry_run: bool):
        limiter.try_acquire("upload", blocking=True)
        return upload_file(file, dry_run)

    with ThreadPoolExecutor(max_workers=min(args.workers, 100)) as executor:
        futures = {
            executor.submit(_rate_limited_upload, f, args.dry_run): f for f in pending
        }
        for future in as_completed(futures):
            file, count, error = future.result()
            if error:
                failed_list.append((file, error))
                console.print(f"[red]✗[/red] {file.name}: {error}")
            else:
                total_rows += count
                succeeded[file.name] = count
                console.print(f"[green]✓[/green] {file.name} ({count} 条)")

    if succeeded and not args.dry_run:
        manifest.update(succeeded)
        manifest.save()

    console.print(f"\n完成: {total_rows} 条记录, {len(failed_list)} 个文件失败")
    if failed_list:
        console.print("[red]失败文件:[/red]")
        for f, err in failed_list:
            console.print(f"  {f.name}: {err}")
