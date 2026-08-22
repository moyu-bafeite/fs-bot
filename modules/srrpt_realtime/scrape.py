"""港交所股份回购公告链接爬虫。

从 HKEX titlesearch 页面爬取指定日期的所有股份回购公告 URL，
解析 HTML 表格并写入 Supabase。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from lib.db import upsert_repurchase_announcements

_POST_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"

_PAYLOAD_TEMPLATE = {
    "lang": "ZH",
    "category": "0",
    "market": "SEHK",
    "searchType": "1",
    "documentType": "-1",
    "t1code": "50000",
    "t2Gcode": "-2",
    "t2code": "50100",
    "stockId": "-1",
    "MB-Daterange": "0",
    "title": "",
}

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 30
_MAX_RETRIES = 3


@dataclass(frozen=True)
class Announcement:
    """单条回购公告记录。"""

    stock_code: str
    stock_name: str
    release_time: str
    document_url: str


@dataclass(frozen=True)
class ScrapeResult:
    """单日爬取结果。"""

    target_date: date
    count: int
    success: bool
    error: str = ""


# ── HTML 解析 ──

# 匹配表格中的一行 <tr>...</tr>
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)

# 匹配 <td> 单元格内容
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)

# 从 document 单元格中提取链接
_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)

# 清除 HTML 标签
_TAG_RE = re.compile(r"<[^>]+>")

# 移除移动端标签 <span class="mobile-list-heading">...</span>
_MOBILE_SPAN_RE = re.compile(
    r'<span\s+class="mobile-list-heading"[^>]*>.*?</span>', re.DOTALL | re.IGNORECASE
)


def _strip_tags(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _clean_cell(cell_html: str, first_line: bool = False) -> str:
    """移除移动端标签后提取纯文本。first_line=True 时只取第一行（处理双柜台）。"""
    cleaned = _MOBILE_SPAN_RE.sub("", cell_html)
    if first_line:
        cleaned = _BR_RE.split(cleaned, maxsplit=1)[0]
    return _strip_tags(cleaned)


def _parse_html(html: str, target_date: date) -> list[Announcement]:
    """从 HKEX titlesearch 响应 HTML 中提取公告记录。"""
    announcements: list[Announcement] = []

    for tr_match in _TR_RE.finditer(html):
        row_html = tr_match.group(1)
        cells = _TD_RE.findall(row_html)
        if len(cells) < 4:
            continue

        release_time = _clean_cell(cells[0])
        stock_code = _clean_cell(cells[1], first_line=True)
        stock_name = _clean_cell(cells[2], first_line=True)

        # 提取文档链接
        href_match = _HREF_RE.search(cells[3])
        if not href_match:
            continue
        document_url = href_match.group(1)
        if document_url.startswith("/"):
            document_url = f"https://www1.hkexnews.hk{document_url}"

        if not stock_code or not release_time:
            continue

        announcements.append(
            Announcement(
                stock_code=stock_code,
                stock_name=stock_name,
                release_time=release_time,
                document_url=document_url,
            )
        )

    return announcements


# ── HTTP 请求 ──


def _post_with_retry(
    url: str,
    payload: dict[str, str],
    max_retries: int = _MAX_RETRIES,
) -> str:
    """发送 POST 请求，指数退避重试。"""
    for attempt in range(max_retries):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(_CONNECT_TIMEOUT, read=_READ_TIMEOUT),
                follow_redirects=True,
            ) as client:
                resp = client.post(url, data=payload)
                resp.raise_for_status()
                return resp.text
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** (attempt + 1)
            time.sleep(wait)
    return ""


# ── 主流程 ──


def scrape_date(d: date) -> tuple[list[Announcement], str | None]:
    """爬取单日回购公告列表，返回 (公告列表, 错误信息或 None)。"""
    payload = {**_PAYLOAD_TEMPLATE, "from": d.strftime("%Y%m%d"), "to": d.strftime("%Y%m%d")}
    try:
        html = _post_with_retry(_POST_URL, payload)
        announcements = _parse_html(html, d)
        return announcements, None
    except Exception as e:
        return [], str(e)


def scrape_and_save(
    start: date,
    end: date,
    console: Console | None = None,
) -> list[ScrapeResult]:
    """遍历日期区间，逐天爬取并写入 Supabase。"""
    con = console or Console()
    dates = _generate_dates(start, end)
    results: list[ScrapeResult] = []

    if not dates:
        con.print("[yellow]无日期需要爬取[/yellow]")
        return results

    con.print(f"共 {len(dates)} 个工作日需要爬取")

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=con,
    ) as progress:
        task_id = progress.add_task("爬取中", total=len(dates))

        for d in dates:
            progress.update(task_id, description=f"爬取 {d.isoformat()}")
            announcements, error = scrape_date(d)

            if error:
                results.append(ScrapeResult(d, 0, False, error))
                con.print(f"[red]✗[/red] {d.isoformat()}: {error}")
            elif announcements:
                records = [
                    {
                        "stock_code": a.stock_code,
                        "release_time": a.release_time,
                        "document_url": a.document_url,
                    }
                    for a in announcements
                ]
                upsert_repurchase_announcements(records)
                results.append(ScrapeResult(d, len(announcements), True))
                con.print(f"[green]✓[/green] {d.isoformat()}: {len(announcements)} 条")
            else:
                results.append(ScrapeResult(d, 0, True))
                con.print(f"[dim]·[/dim] {d.isoformat()}: 无数据")

            progress.advance(task_id)

    ok = sum(1 for r in results if r.success)
    fail = len(results) - ok
    total = sum(r.count for r in results)
    con.print(f"\n完成: {ok} 天成功, {fail} 天失败, 共 {total} 条公告")

    return results


def _generate_dates(start: date, end: date) -> list[date]:
    """生成工作日列表。"""
    dates: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates
