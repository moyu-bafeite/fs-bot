"""Supabase Storage 操作：上传 PDF 文件。"""

from __future__ import annotations

import os

from supabase import create_client

_url = os.environ["SUPABASE_URL"]
_key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
_client = create_client(_url, _key)

BUCKET = "hkex-reports"


def upload_pdf(
    stock_code: str,
    filing_type: str,
    report_year: int | None,
    news_id: str,
    file_bytes: bytes,
) -> str:
    """上传 PDF 到 Supabase Storage，返回存储路径。"""
    year = report_year or "unknown"
    path = f"{stock_code}/{filing_type}/{year}_{news_id}.pdf"
    _client.storage.from_(BUCKET).upload(
        path=path,
        file=file_bytes,
        file_options={"content-type": "application/pdf"},
    )
    return path
