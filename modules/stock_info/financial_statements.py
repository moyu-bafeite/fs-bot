"""港交所财务报表公告爬虫。

从 HKEX titlesearch 页面爬取指定股票的业绩公告或年报/中报，
用 DeepSeek 解析 HTML 为结构化 JSON 后用 rich 打印。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date

import httpx
from openai import OpenAI
from rich.console import Console
from rich.table import Table

from lib.db import get_stock_meta_by_code

_POST_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"

_REPORT_PAYLOAD = {
    "lang": "ZH",
    "category": "0",
    "market": "SEHK",
    "searchType": "1",
    "documentType": "-1",
    "t1code": "40000",
    "t2Gcode": "-2",
    "t2code": "-2",
    "stockId": "-1",
    "from": "20100101",
    "MB-Daterange": "0",
}

_ANNOUNCEMENT_PAYLOADS = {
    "季度业绩": {
        "lang": "ZH",
        "category": "0",
        "market": "SEHK",
        "searchType": "1",
        "documentType": "-1",
        "t1code": "10000",
        "t2Gcode": "3",
        "t2code": "13600",
        "stockId": "-1",
        "from": "20100101",
        "MB-Daterange": "0",
        "title": "",
    },
    "中期业绩": {
        "lang": "ZH",
        "category": "0",
        "market": "SEHK",
        "searchType": "1",
        "documentType": "-1",
        "t1code": "10000",
        "t2Gcode": "3",
        "t2code": "13400",
        "stockId": "-1",
        "from": "20100101",
        "MB-Daterange": "0",
        "title": "",
    },
    "末期业绩": {
        "lang": "ZH",
        "category": "0",
        "market": "SEHK",
        "searchType": "1",
        "documentType": "-1",
        "t1code": "10000",
        "t2Gcode": "3",
        "t2code": "13300",
        "stockId": "-1",
        "from": "20100101",
        "MB-Daterange": "0",
        "title": "",
    },
}

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 30
_MAX_RETRIES = 3

_REPORT_PROMPT = """\
你是港交所财务报表公告 HTML 解析器。

从 HKEX titlesearch 返回的 HTML 表格中提取所有公告记录。

每条记录包含以下字段：
- date: 发布日期（转换成 2024-03-28 这种 YYYY-MM-DD 格式）
- doc_type: 文件类型，根据文件标题判断，只保留以下两种：
  - "年报" — 标题含 "年度業績" 或 "Annual Results" 或 "年報" 或 "Annual Report"
  - "中报" — 标题含 "中期業績" 或 "Interim Results" 或 "中期報告" 或 "Interim Report"
  - 其他类型（如 "環境、社會及管治資料"、"季度業績" 等）一律排除
- doc_url: 文件链接（完整 URL，若为相对路径则补全为 https://www1.hkexnews.hk 前缀）

输出严格的 JSON 对象，格式：
{"records": [<record>, ...]}

若无符合条件的记录，输出 {"records": []}
只输出 JSON，不要其他内容。
"""

_ANNOUNCEMENT_PROMPT = """\
你是港交所业绩公告 HTML 解析器。

从 HKEX titlesearch 返回的 HTML 表格中提取所有业绩公告记录。

每条记录包含以下字段：
- date: 发布日期（转换成 2024-03-28 这种 YYYY-MM-DD 格式）
- doc_type: 文件类型，根据搜索类别固定为以下之一：
  - "季度業績"
  - "中期業績"
  - "末期業績"
- doc_url: 文件链接（完整 URL，若为相对路径则补全为 https://www1.hkexnews.hk 前缀）

输出严格的 JSON 对象，格式：
{"records": [<record>, ...]}

若无符合条件的记录，输出 {"records": []}
只输出 JSON，不要其他内容。
"""


@dataclass(frozen=True)
class FinancialStatementResult:
    """查询结果。"""

    stock_code: str
    stock_name: str
    records: list[dict]


class FinancialStatementHandler:
    """财务报表公告查询与展示。"""

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )

    def fetch(self, ticker: str, doc_type: str = "report") -> FinancialStatementResult:
        """查询指定股票的财务报表/业绩公告，返回结构化数据。

        Args:
            ticker: 股票代码
            doc_type: "report" 查询年报/中报，"announcement" 查询业绩公告
        """
        stock_code = self._normalize_ticker(ticker)

        meta = get_stock_meta_by_code(stock_code)
        if not meta:
            raise ValueError(
                f"未找到股票 {stock_code}，请先运行 hkex_stock_data 同步股票列表"
            )

        hkex_id = str(meta["hkex_id"])
        stock_name_obj = meta.get("stock_name", {})
        stock_name = (
            stock_name_obj.get("zh-CN") if isinstance(stock_name_obj, dict) else ""
        ) or stock_code

        if doc_type == "announcement":
            records = self._fetch_announcements(hkex_id)
        else:
            records = self._fetch_reports(hkex_id)

        return FinancialStatementResult(
            stock_code=stock_code,
            stock_name=stock_name,
            records=records,
        )

    def display(
        self, result: FinancialStatementResult, console: Console | None = None
    ) -> None:
        """用 rich 表格打印查询结果。"""
        con = console or Console()

        if not result.records:
            con.print(
                f"[yellow]未找到 {result.stock_name} ({result.stock_code}) 的相关记录[/yellow]"
            )
            return

        sorted_records = sorted(
            result.records, key=lambda r: r.get("date", ""), reverse=True
        )

        table = Table(
            title=f"{result.stock_name} ({result.stock_code})", show_lines=True
        )
        table.add_column("#", style="dim", width=6)
        table.add_column("日期", style="cyan", width=16)
        table.add_column("文件类型", width=10)
        table.add_column("链接", style="blue", overflow="fold")

        for i, rec in enumerate(sorted_records, 1):
            table.add_row(
                str(i),
                rec.get("date", ""),
                rec.get("doc_type", ""),
                rec.get("doc_url", ""),
            )

        con.print(table)
        con.print(f"共 {len(sorted_records)} 条记录")

    def _fetch_reports(self, hkex_id: str) -> list[dict]:
        payload = {**_REPORT_PAYLOAD, "stockId": hkex_id}
        html = self._post(payload)
        return self._parse_with_llm(html, _REPORT_PROMPT)

    def _fetch_announcements(self, hkex_id: str) -> list[dict]:
        # 先搜季度业绩
        quarterly = {**_ANNOUNCEMENT_PAYLOADS["季度业绩"], "stockId": hkex_id}
        html = self._post(quarterly)
        records = self._parse_with_llm(html, _ANNOUNCEMENT_PROMPT)
        for r in records:
            r["doc_type"] = "季度业绩"

        if records:
            return records

        # 季度无结果，同时搜中期和末期
        for label in ("中期业绩", "末期业绩"):
            payload = {**_ANNOUNCEMENT_PAYLOADS[label], "stockId": hkex_id}
            html = self._post(payload)
            batch = self._parse_with_llm(html, _ANNOUNCEMENT_PROMPT)
            for r in batch:
                r["doc_type"] = label
            records.extend(batch)

        return records

    def _post(self, payload: dict[str, str]) -> str:
        payload = {**payload, "to": date.today().strftime("%Y%m%d")}
        for attempt in range(_MAX_RETRIES):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(_CONNECT_TIMEOUT, read=_READ_TIMEOUT),
                    follow_redirects=True,
                ) as client:
                    resp = client.post(_POST_URL, data=payload)
                    resp.raise_for_status()
                    return resp.text
            except (httpx.HTTPStatusError, httpx.RequestError):
                if attempt == _MAX_RETRIES - 1:
                    raise
                time.sleep(2 ** (attempt + 1))
        return ""

    def _parse_with_llm(self, html: str, system_prompt: str) -> list[dict]:
        resp = self._client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": html},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or '{"records": []}'
        data = json.loads(content)
        if isinstance(data, list):
            return data
        return data.get("records", [])

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        code = ticker.strip()
        if code.isdigit():
            return code.zfill(5)
        return code
