"""港交所回购报告 ETL CLI。

子命令:
  download - 批量下载 SRRPT .xls 文件
  parse    - 解析 .xls 为 JSON/CSV
  upload   - 上传 JSON 到 Supabase
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

import typer

app = typer.Typer(help="港交所回购报告 ETL")


@app.command()
def download(
    start: Annotated[datetime, typer.Option(help="起始日期")] = ...,
    end: Annotated[datetime, typer.Option(help="结束日期")] = ...,
    output_dir: Annotated[str, typer.Option(help="输出目录")] = "",
    workers: Annotated[int, typer.Option(help="并发线程数")] = 5,
    no_skip: Annotated[bool, typer.Option("--no-skip", help="不跳过已存在的文件")] = False,
):
    """批量下载 SRRPT .xls 文件。"""
    from rich.console import Console

    from modules.srrpt.download import HKEXSrrptDownloader

    console = Console()
    kwargs: dict = {
        "console": console,
        "workers": workers,
        "skip_existing": not no_skip,
    }
    if output_dir:
        kwargs["output_dir"] = output_dir

    dl = HKEXSrrptDownloader(**kwargs)
    results = dl.download_range(start.date(), end.date())

    failed = [r for r in results if not r.success]
    if failed:
        console.print(f"\n[red]{len(failed)} 个文件下载失败:[/red]")
        for r in failed:
            console.print(f"  {r.target_date}: {r.error}")


@app.command()
def parse(
    file: Annotated[str, typer.Argument(help=".xls 文件路径（为空则批量解析）")] = "",
    json_format: Annotated[bool, typer.Option("--json", help="输出 JSON 格式")] = False,
    csv_format: Annotated[bool, typer.Option("--csv", help="输出 CSV 格式")] = False,
    output: Annotated[str, typer.Option("-o", help="输出文件路径")] = "",
    workers: Annotated[int, typer.Option(help="并发线程数")] = 100,
):
    """解析 .xls 为 JSON/CSV。"""
    from pathlib import Path
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from rich.console import Console
    from modules.srrpt.parse import HKEXSrrptParser

    console = Console()
    fmt = "json" if json_format else "csv"

    if not file:
        input_dir = Path("downloads/srrpt")
        output_dir = Path(output) if output else Path("output/srrpt")
        files = sorted(input_dir.glob("*.xls"))
        if not files:
            console.print(f"[yellow]未找到 .xls 文件: {input_dir}[/yellow]")
            return
        output_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"共 {len(files)} 个文件，输出目录: {output_dir}")

        max_workers = min(workers, 100)
        failed_list: list[tuple[Path, str]] = []

        def _process(f: Path):
            try:
                p = HKEXSrrptParser(f)
                p.load()
                stem = f.stem
                if fmt == "json":
                    p.save_json(output_dir / f"{stem}.json")
                else:
                    p.save_csv(output_dir / f"{stem}.csv")
                return f, None
            except Exception as e:
                return f, str(e)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_process, f): f for f in files}
            for future in as_completed(futures):
                f, error = future.result()
                if error:
                    failed_list.append((f, error))
                    console.print(f"[red]✗[/red] {f.name}: {error}")
                else:
                    console.print(f"[green]✓[/green] {f.name}")

        console.print(
            f"\n完成: {len(files) - len(failed_list)} 成功, {len(failed_list)} 失败"
        )
        if failed_list:
            console.print("[red]失败文件:[/red]")
            for f, err in failed_list:
                console.print(f"  {f.name}: {err}")
        return

    target = Path(file)
    parser = HKEXSrrptParser(target)
    parser.load()

    out = Path(output) if output else None
    if json_format:
        if out:
            parser.save_json(out)
            console.print(f"[green]已保存 JSON 到 {out}[/green]")
        else:
            print(parser.to_json())
    elif csv_format:
        if out:
            parser.save_csv(out)
            console.print(f"[green]已保存 CSV 到 {out}[/green]")
        else:
            print(parser.to_csv())
    else:
        parser.print(console)


@app.command()
def upload(
    file: Annotated[str, typer.Option(help="指定单个 JSON 文件")] = "",
    input_dir: Annotated[str, typer.Option(help="JSON 文件目录")] = "",
    workers: Annotated[int, typer.Option(help="并发线程数")] = 100,
    dry_run: Annotated[bool, typer.Option(help="仅打印，不实际插入")] = False,
):
    """上传 JSON 到 Supabase。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pathlib import Path
    from rich.console import Console
    from lib.manifest import MANIFEST_NAME, Manifest
    from lib.db import upsert_repurchase_reports
    from modules.srrpt.upload import read_json_file

    console = Console()
    PAGE_SIZE = 1000

    if file:
        files = [Path(file)]
        manifest_path = files[0].parent / MANIFEST_NAME
    else:
        in_dir = Path(input_dir) if input_dir else Path("output/srrpt")
        files = sorted(f for f in in_dir.glob("*.json") if f.name != MANIFEST_NAME)
        manifest_path = in_dir / MANIFEST_NAME

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
    if dry_run:
        console.print("[yellow]DRY RUN 模式[/yellow]")

    all_rows: list[dict] = []
    failed_reads: list[tuple[Path, str]] = []
    file_row_counts: dict[str, int] = {}

    def _read_file(f: Path):
        try:
            rows = read_json_file(f)
            return f, rows, None
        except Exception as e:
            return f, [], str(e)

    with ThreadPoolExecutor(max_workers=min(workers, 100)) as executor:
        futures = {executor.submit(_read_file, f): f for f in pending}
        for future in as_completed(futures):
            f, rows, error = future.result()
            if error:
                failed_reads.append((f, error))
                console.print(f"[red]✗[/red] 读取失败 {f.name}: {error}")
            else:
                file_row_counts[f.name] = len(rows)
                all_rows.extend(rows)
                console.print(f"[green]✓[/green] {f.name} ({len(rows)} 条)")

    if not all_rows:
        console.print("[yellow]无数据可上传[/yellow]")
        return

    console.print(f"\n共读取 {len(all_rows)} 条记录")

    if dry_run:
        console.print("[yellow]DRY RUN 模式，跳过上传[/yellow]")
        return

    total_inserted = 0
    failed_inserts: list[str] = []
    pages = (len(all_rows) + PAGE_SIZE - 1) // PAGE_SIZE

    for i in range(0, len(all_rows), PAGE_SIZE):
        page = all_rows[i : i + PAGE_SIZE]
        page_num = i // PAGE_SIZE + 1
        try:
            count = upsert_repurchase_reports(page)
            total_inserted += count
            console.print(f"[green]✓[/green] 第 {page_num}/{pages} 页 ({count} 条)")
        except Exception as e:
            failed_inserts.append(f"第 {page_num} 页: {e}")
            console.print(f"[red]✗[/red] 第 {page_num}/{pages} 页: {e}")

    if not failed_inserts and not failed_reads:
        manifest.update(file_row_counts)
        manifest.save()

    console.print(f"\n完成: {total_inserted} 条记录插入")
    if failed_reads:
        console.print("[red]读取失败:[/red]")
        for f, err in failed_reads:
            console.print(f"  {f.name}: {err}")
    if failed_inserts:
        console.print("[red]插入失败:[/red]")
        for err in failed_inserts:
            console.print(f"  {err}")
