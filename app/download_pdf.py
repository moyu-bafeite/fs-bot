"""轮询 pending 记录，下载 PDF 并上传到 Supabase Storage。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from lib.db import get_pending_filings, log_error, update_filing_status
from lib.storage import upload_pdf
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


def download(
    tickers: list[str] | None = None,
    limit: int = 50,
    max_workers: int = 5,
) -> int:
    """处理 pending 记录，返回成功下载数。"""
    success = 0

    if tickers:
        pending: list[dict] = []
        for ticker in tickers:
            code = ticker.strip().upper()
            if code.endswith(".HK"):
                code = code[:-3]
            code = code.lstrip("0").zfill(5)
            pending.extend(get_pending_filings(stock_code=code, limit=limit))
    else:
        pending = get_pending_filings(limit=limit)

    if not pending:
        print("没有 pending 记录")
        return 0

    def _process_one(filing: dict) -> str:
        fid = filing["id"]
        code = filing["stock_code"]
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            resp = client.get(filing["file_url"])
            resp.raise_for_status()
            pdf_path = upload_pdf(
                stock_code=code,
                filing_type=filing["filing_type"],
                report_year=filing.get("report_year"),
                news_id=filing["news_id"],
                file_bytes=resp.content,
            )
            update_filing_status(fid, "downloaded", pdf_path=pdf_path)
            return pdf_path

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    ) as progress:
        task_id = progress.add_task("下载 PDF", total=len(pending))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process_one, filing): filing for filing in pending
            }
            for future in as_completed(futures):
                filing = futures[future]
                try:
                    future.result()
                    success += 1
                except Exception as e:
                    update_filing_status(filing["id"], "failed")
                    log_error(
                        "download",
                        str(e),
                        filing_id=filing["id"],
                        stock_code=filing["stock_code"],
                    )
                progress.advance(task_id)

    return success


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="下载 pending 的 PDF 并上传 Storage")
    parser.add_argument("--tickers", nargs="+", help="只处理指定股票")
    parser.add_argument("--limit", type=int, default=50, help="最大处理数量")
    parser.add_argument("--workers", type=int, default=5, help="并发下载数")
    return parser
