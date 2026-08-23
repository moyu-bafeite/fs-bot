"""港交所回购公告 PDF 解析器。

遍历 hkex_repurchase_announcements 中 parsed=FALSE 的记录，
下载 PDF → pdfplumber 提取文本 → DeepSeek V4 Flash 解析为结构化 JSON。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import httpx
import pdfplumber
from openai import OpenAI
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from lib.db import (
    get_unparsed_announcements,
    insert_realtime_reports,
    mark_announcement_parsed,
)

_DOWNLOAD_DIR = Path("downloads/srann")
_OUTPUT_DIR = Path("output/srann")
_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 60
_MAX_RETRIES = 3

_SYSTEM_PROMPT = """\
You are a Hong Kong listed company share repurchase report (Next Day Disclosure Return) parser.

Extract basic info from Section 1.
- Date Submitted → report_date
- Stock code (if listed) → stock_code (5-digit number)
- Class of shares → sec_type

Extract all repurchase transaction records from Section 2 (Repurchase Report).

PDF structure:
- Section 2 contains "A. Repurchase Report" tables with multiple transactions
- Table columns: Trading date | Number of shares repurchased | Method of repurchase | Lowest price per share | Hightest price per share | Aggregate price paid
- Method may include exchange name, e.g. "On another stock exchange\\nLondon Stock Exchange"
- Price prefix is the currency code (GBP / HKD / USD etc.)
- If highest price = lowest price, it is a VWAP; fill both fields with the same value
- Number of shares repurchased (for cancellation) → for_cancellation
- Number of shares repurchased (to be held as treasury shares) → for_treasury
- Number of shares repurchased pursuant to the mandate → cumulative_quantity (0 if empty)
- Percentage of issued shares at mandate resolution date → cumulative_pct (0 if empty)

Output a strict JSON array. Each record must have these fields:
- report_date: Date of Submission (YYYY-MM-DD)
- stock_code: Stock Code (5-digit string)
- sec_type: Class of Securities (e.g. "ORD" / "PRF")
- trade_date: Date of transaction (YYYY-MM-DD)
- quantity: Number of shares repurchased (integer)
- high_price: Highest price per share (float)
- low_price: Lowest price per share (float)
- currency: Currency code ("HKD" / "GBP" / "USD" etc.)
- amount: Aggregate price paid (float)
- method: Method of repurchase
- for_cancellation: Number of shares repurchased for cancellation (integer, 0 if absent)
- for_treasury: Number of shares repurchased to be held as treasury shares (integer, 0 if absent)
- cumulative_quantity: Number of shares repurchased pursuant to the mandate (integer, 0 if absent)
- cumulative_pct: Percentage of issued shares at mandate resolution date (float, 0 if absent)

Rules:
1. Extract ALL transaction records from Section 2, each "A. Repurchase Report" table independently
2. Remove commas from numbers ("1,234" → 1234)
3. Preserve original price precision
4. Use default value 0 or empty string for missing fields
5. Output ONLY the JSON array, nothing else
"""


@dataclass(frozen=True)
class ParseResult:
    """单条公告的解析结果。"""

    stock_code: str
    release_time: str
    document_url: str
    records_count: int
    success: bool
    error: str = ""


def _download_pdf(url: str, dest: Path, max_retries: int = _MAX_RETRIES) -> None:
    """下载 PDF 文件，指数退避重试。"""
    for attempt in range(max_retries):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(_CONNECT_TIMEOUT, read=_READ_TIMEOUT),
                follow_redirects=True,
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                return
        except (httpx.HTTPStatusError, httpx.RequestError):
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def _extract_text(pdf_path: Path) -> str:
    """用 pdfplumber 提取 PDF 全文。"""
    texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
    return "\n".join(texts)


def _parse_with_llm(client: OpenAI, text: str) -> list[dict]:
    """调用 DeepSeek V4 Flash 解析文本为结构化记录。"""
    resp = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
        response_format={
            'type': 'json_object'
        }
    )
    content = resp.choices[0].message.content or "[]"

    # 提取 JSON 数组（兼容 markdown 代码块）
    if "```" in content:
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            content = content[start:end]

    return json.loads(content)


_REQUIRED_FIELDS = {
    "report_date": str,
    "stock_code": str,
    "sec_type": str,
    "trade_date": str,
    "quantity": (int, float),
    "high_price": (int, float),
    "low_price": (int, float),
    "currency": str,
    "amount": (int, float),
    "method": str,
    "for_cancellation": (int, float),
    "for_treasury": (int, float),
    "cumulative_quantity": (int, float),
    "cumulative_pct": (int, float),
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STOCK_CODE_RE = re.compile(r"^\d{5}$")
_CURRENCIES = {"HKD", "GBP", "USD", "RMB", "EUR", "SGD", "CNY", "JPY"}


def _validate_records(records: list[dict]) -> list[str]:
    """校验 LLM 输出的记录，返回错误列表（空=全部通过）。"""
    errors: list[str] = []
    for i, rec in enumerate(records):
        prefix = f"record[{i}]"
        # 必填字段 + 类型
        for field, expected_type in _REQUIRED_FIELDS.items():
            val = rec.get(field)
            if val is None:
                errors.append(f"{prefix}: 缺少字段 {field}")
                continue
            if not isinstance(val, expected_type):
                errors.append(f"{prefix}: {field} 类型错误，期望 {expected_type}，实际 {type(val).__name__}")

        # 日期格式
        for date_field in ("report_date", "trade_date"):
            val = rec.get(date_field, "")
            if val and not _DATE_RE.match(str(val)):
                errors.append(f"{prefix}: {date_field} 格式无效 '{val}'，应为 YYYY-MM-DD")

        # 股票代码
        code = str(rec.get("stock_code", ""))
        if code and not _STOCK_CODE_RE.match(code):
            errors.append(f"{prefix}: stock_code 格式无效 '{code}'，应为5位数字")

        # 数值合理性
        qty = rec.get("quantity", 0)
        if isinstance(qty, (int, float)) and qty < 0:
            errors.append(f"{prefix}: quantity 不能为负 ({qty})")
        amount = rec.get("amount", 0)
        if isinstance(amount, (int, float)) and amount < 0:
            errors.append(f"{prefix}: amount 不能为负 ({amount})")

    return errors


def _filename_from_url(url: str, stock_code: str) -> str:
    """从 URL 生成本地 PDF 文件名。"""
    name = url.rsplit("/", 1)[-1]
    return f"{stock_code}_{name}"


def _dedup_key(rec: dict) -> tuple:
    """记录去重键：(stock_code, trade_date, quantity, amount)。"""
    return (rec.get("stock_code", ""), rec.get("trade_date", ""), rec.get("quantity", 0), rec.get("amount", 0))


def _merge_records(existing: list[dict], new: list[dict]) -> list[dict]:
    """合并新旧记录，按 dedup_key 去重（新数据优先）。"""
    seen: dict[tuple, dict] = {}
    for rec in existing:
        seen[_dedup_key(rec)] = rec
    for rec in new:
        seen[_dedup_key(rec)] = rec
    return sorted(seen.values(), key=lambda r: (r.get("stock_code", ""), r.get("trade_date", "")))


def parse_all(
    console: Console | None = None,
    workers: int = 5,
    push: bool = False,
) -> list[ParseResult]:
    """遍历所有未解析公告，多线程下载 PDF → LLM 解析 → 按 trade_date 保存 JSON。"""
    con = console or Console()
    _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    announcements = get_unparsed_announcements()
    if not announcements:
        con.print("[yellow]无待解析公告[/yellow]")
        return []

    con.print(f"共 {len(announcements)} 条待解析公告（{workers} 线程）")

    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )

    results: list[ParseResult] = []
    # 按 trade_date 收集所有记录
    date_records: dict[str, list[dict]] = {}
    lock = threading.Lock()

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=con,
    ) as progress:
        task_id = progress.add_task("解析中", total=len(announcements))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_parse_one, client, ann): ann
                for ann in announcements
            }
            for future in as_completed(futures):
                result, records = future.result()
                with lock:
                    results.append(result)
                    if result.success and records:
                        for rec in records:
                            td = rec.get("trade_date", "")
                            if td:
                                date_records.setdefault(td, []).append(rec)
                    label = f"{result.stock_code} {result.release_time[:10]}"
                    if result.success:
                        con.print(
                            f"[green]✓[/green] {label}: {result.records_count} 条记录"
                        )
                    else:
                        con.print(f"[red]✗[/red] {label}: {result.error}")
                    progress.advance(task_id)

    # 按 trade_date 增量合并写入文件
    for td, new_records in sorted(date_records.items()):
        out_path = _OUTPUT_DIR / f"{td.replace('-', '')}.json"
        existing: list[dict] = []
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = []
        merged = _merge_records(existing, new_records)
        out_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 推送到 Supabase 实时表
    if push and date_records:
        all_records = [r for recs in date_records.values() for r in recs]
        count = insert_realtime_reports(all_records)
        con.print(f"[green]✓[/green] 已推送 {count} 条记录到 hkex_repurchase_realtime_reports")

    ok = sum(1 for r in results if r.success)
    fail = len(results) - ok
    total = sum(r.records_count for r in results if r.success)
    con.print(f"\n完成: {ok} 成功, {fail} 失败, 共 {total} 条记录, {len(date_records)} 个日期文件")

    return results


def _parse_one(client: OpenAI, ann: dict) -> tuple[ParseResult, list[dict]]:
    """处理单条公告：下载 → 提取 → LLM 解析 → 校验。返回 (结果, 有效记录)。"""
    stock_code = ann["stock_code"]
    release_time = ann["release_time"]
    document_url = ann["document_url"]

    filename = _filename_from_url(document_url, stock_code)
    pdf_path = _DOWNLOAD_DIR / filename

    def _fail(error: str) -> tuple[ParseResult, list[dict]]:
        return ParseResult(stock_code, release_time, document_url, 0, False, error), []

    try:
        # 1. 下载 PDF
        if not pdf_path.exists():
            _download_pdf(document_url, pdf_path)

        # 2. 提取文本
        text = _extract_text(pdf_path)
        if not text.strip():
            return _fail("PDF 无文本内容")

        # 3. LLM 解析
        records = _parse_with_llm(client, text)

        # 4. Post Process
        for record in records:
            record["stock_code"] = stock_code

        # 5. Schema 校验
        errors = _validate_records(records)
        if errors:
            return _fail(f"校验失败 ({len(errors)} 项): {errors[0]}")

        # 6. 标记已解析
        mark_announcement_parsed(stock_code, release_time, document_url)

        return (
            ParseResult(stock_code, release_time, document_url, len(records), True),
            records,
        )

    except Exception as e:
        return _fail(str(e))
