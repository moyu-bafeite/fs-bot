"""HKEX JSON API 交互：获取 ViewState、按月分页查询文件列表。"""

from __future__ import annotations

import json
import re
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

HKEX_SEARCH_PAGE = "https://www1.hkexnews.hk/search/titlesearch.xhtml"
HKEX_API_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
HKEX_BASE_URL = "https://www1.hkexnews.hk"
HKEX_STOCK_LIST_URL = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json"

_API_CHUNK_SIZE = 5000


def get_stock_id_map() -> dict[str, int]:
    """获取股票代码到内部 ID 的映射表。始终从 HKEX API 获取最新数据。"""
    resp = httpx.get(HKEX_STOCK_LIST_URL, timeout=30)
    resp.raise_for_status()
    stocks = resp.json()
    return {item["c"]: item["i"] for item in stocks}


def _generate_monthly_chunks(
    date_from: datetime, date_to: datetime
) -> list[tuple[datetime, datetime]]:
    """按月分块（从新到旧），HKEX API 限制单次查询范围。"""
    chunks: list[tuple[datetime, datetime]] = []
    cursor = datetime(date_to.year, date_to.month, 1)
    while cursor >= datetime(date_from.year, date_from.month, 1):
        chunk_start = max(cursor, date_from)
        _, last_day = monthrange(cursor.year, cursor.month)
        chunk_end = min(datetime(cursor.year, cursor.month, last_day), date_to)
        chunks.append((chunk_start, chunk_end))
        if cursor.month == 1:
            cursor = datetime(cursor.year - 1, 12, 1)
        else:
            cursor = datetime(cursor.year, cursor.month - 1, 1)
    return chunks


def _fetch_chunk(
    client: httpx.Client,
    stock_id: int,
    date_from: datetime,
    date_to: datetime,
) -> list[dict]:
    """获取单个月份分块的指定股票定期报告。

    t1code=40000: Financial Statements/ESG Information
    t2code=-2: 全部子类（年报+中报+季报+ESG）
    """
    from_str = date_from.strftime("%Y%m%d")
    to_str = date_to.strftime("%Y%m%d")

    # Step 1: GET 搜索页面，获取 ViewState
    page_resp = client.get(
        HKEX_SEARCH_PAGE,
        params={
            "lang": "EN",
            "market": "SEHK",
            "stockId": str(stock_id),
            "category": "0",
            "sortDir": "0",
            "sortByRecordDate": "on",
            "searchType": "0",
            "t1code": "40000",
            "t2Gcode": "-2",
            "t2code": "-2",
            "documentType": "-1",
            "rowRange": "0",
        },
        timeout=30,
    )
    page_resp.raise_for_status()

    soup = BeautifulSoup(page_resp.text, "html.parser")
    vs_el = soup.find("input", {"name": "javax.faces.ViewState"})
    view_state = str(vs_el["value"]) if vs_el else ""
    form_el = soup.find("form")
    form_action = str(form_el.get("action", "")) if form_el else ""

    submit_url = (
        f"{HKEX_BASE_URL}{form_action}" if form_action.startswith("/") else form_action
    )

    # Step 2: POST 表单设置日期范围
    client.post(
        submit_url,
        data={
            "j_idt12": "j_idt12",
            "j_idt12:loadMoreRange": "100",
            "javax.faces.ViewState": view_state,
            "from": from_str,
            "to": to_str,
        },
        timeout=30,
    )

    # Step 3: GET JSON API 分页获取记录
    all_records: list[dict] = []
    fetched = 0

    while True:
        row_range = fetched + _API_CHUNK_SIZE
        api_resp = client.get(
            HKEX_API_URL,
            params={
                "sortDir": "0",
                "sortByOptions": "DateTime",
                "category": "0",
                "market": "SEHK",
                "stockId": str(stock_id),
                "documentType": "-1",
                "fromDate": from_str,
                "toDate": to_str,
                "title": "",
                "searchType": "0",
                "t1code": "40000",
                "t2Gcode": "-2",
                "t2code": "-2",
                "rowRange": str(row_range),
                "lang": "E",
            },
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": HKEX_SEARCH_PAGE,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=120,
        )
        if api_resp.status_code == 404:
            break
        api_resp.raise_for_status()

        data = api_resp.json()
        raw_result = data.get("result", "null")
        if not raw_result or raw_result == "null":
            break

        records = json.loads(raw_result)
        new_records = records[fetched:]
        for rec in new_records:
            all_records.append(_parse_record(rec))
        fetched = len(records)

        if not data.get("hasNextRow", False):
            break

    return all_records


def _parse_record(record: dict) -> dict:
    """将 HKEX API 原始记录转为标准格式。"""
    date_time = record.get("DATE_TIME", "")
    date_part = date_time.split(" ")[0] if date_time else ""

    raw_code = record.get("STOCK_CODE", "")
    raw_code = raw_code.split("<br/>")[0].strip()

    raw_name = record.get("STOCK_NAME", "")
    raw_name = raw_name.split("<br/>")[0].strip()

    file_link = record.get("FILE_LINK", "")
    if file_link and file_link.startswith("/"):
        file_link = HKEX_BASE_URL + file_link

    title = record.get("TITLE", "")
    title = title.replace("&#x3b;", ";").replace("&amp;", "&")

    # 从 LONG_TEXT 或标题判断 filing_type
    long_text = record.get("LONG_TEXT", "")
    filing_type = _detect_filing_type(title, long_text)

    return {
        "news_id": record.get("NEWS_ID", ""),
        "stock_code": raw_code,
        "stock_name": _squash_ws(raw_name),
        "title": _squash_ws(title),
        "filing_type": filing_type,
        "file_type": record.get("FILE_TYPE", ""),
        "file_url": file_link,
        "file_size": record.get("FILE_INFO", ""),
        "date_time": date_part,
    }


def _detect_filing_type(title: str, long_text: str) -> str:
    """从标题或分类文本判断是年报还是中报。"""
    combined = f"{title} {long_text}".lower()
    if "interim" in combined or "half-year" in combined or "half year" in combined:
        return "interim"
    if "annual" in combined:
        return "annual"
    # 默认按标题中的年份和月份推断
    return "annual"


def _squash_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fetch_filings(
    stock_code: str,
    date_from: datetime,
    date_to: datetime,
    max_workers: int = 3,
) -> list[dict]:
    """获取指定股票在日期范围内的所有文件记录。"""
    now = datetime.now()
    if date_to > now:
        date_to = now

    stock_id_map = get_stock_id_map()
    stock_id = stock_id_map.get(stock_code)
    if stock_id is None:
        return []

    chunks = _generate_monthly_chunks(date_from, date_to)
    total = len(chunks)
    all_records: list[dict] = []

    def _process_chunk(chunk_from: datetime, chunk_to: datetime) -> list[dict]:
        with httpx.Client(follow_redirects=True) as client:
            return _fetch_chunk(client, stock_id, chunk_from, chunk_to)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    ) as progress:
        task_id = progress.add_task(f"爬取 {stock_code}", total=total)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process_chunk, cf, ct): (cf, ct) for cf, ct in chunks
            }
            for future in as_completed(futures):
                records = future.result()
                all_records.extend(records)
                progress.advance(task_id)

    return all_records
