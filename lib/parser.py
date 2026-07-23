"""标题筛选、报告类型识别、ticker 格式清洗。"""

from __future__ import annotations

import re

# 年报关键词
_ANNUAL_PATTERNS = re.compile(r"Annual\s+Report|Annual\s+Results", re.IGNORECASE)
# 中报关键词
_INTERIM_PATTERNS = re.compile(
    r"Interim\s+Report|Interim\s+Results|Half[- ]Year", re.IGNORECASE
)
# 排除摘要版
_SUMMARY_PATTERN = re.compile(r"Summary\s+Financial\s+Report", re.IGNORECASE)


def normalize_ticker(ticker: str) -> str:
    """清洗 ticker 格式：去 .HK 后缀、补零至 5 位。"""
    code = ticker.strip().upper()
    if code.endswith(".HK"):
        code = code[:-3]
    code = code.lstrip("0") or "0"
    return code.zfill(5)


def classify_filing(
    title: str, exclude_pattern: re.Pattern[str] | None = None
) -> str | None:
    """判断文件类型，返回 'annual' / 'interim' / None。"""
    if _SUMMARY_PATTERN.search(title):
        return None
    if exclude_pattern and exclude_pattern.search(title):
        return None
    if _ANNUAL_PATTERNS.search(title):
        return "annual"
    if _INTERIM_PATTERNS.search(title):
        return "interim"
    return None


def extract_report_year(title: str, date_str: str) -> int | None:
    """从标题或日期中提取报告年份。优先从标题提取 4 位年份。"""
    # 从标题找 4 位年份（如 "Annual Report 2025"）
    match = re.search(r"(20\d{2})", title)
    if match:
        return int(match.group(1))
    # 回退到披露日期的年份
    if date_str:
        parts = date_str.split("/")
        if len(parts) == 3:
            try:
                return int(parts[2])
            except ValueError:
                pass
    return None


def build_exclude_pattern(keywords: list[str]) -> re.Pattern[str] | None:
    """将关键词列表编译为排除正则，空列表返回 None。"""
    if not keywords:
        return None
    escaped = [re.escape(kw) for kw in keywords]
    return re.compile("|".join(escaped), re.IGNORECASE)


def filter_annual_and_interim(
    records: list[dict],
    exclude_pattern: re.Pattern[str] | None = None,
) -> list[dict]:
    """从 HKEX 文件列表中筛选年报和中报，返回结构化记录。"""
    results: list[dict] = []
    for rec in records:
        filing_type = classify_filing(rec["title"], exclude_pattern)
        if filing_type is None:
            continue
        report_year = extract_report_year(rec["title"], rec.get("date_time", ""))
        results.append(
            {
                "news_id": rec["news_id"],
                "stock_code": rec["stock_code"],
                "stock_name": rec["stock_name"],
                "title": rec["title"],
                "filing_type": filing_type,
                "report_year": report_year,
                "filing_date": _parse_date(rec.get("date_time", "")),
                "file_url": rec["file_url"],
                "status": "pending",
            }
        )
    return results


def _parse_date(date_str: str) -> str:
    """将 DD/MM/YYYY 转为 YYYY-MM-DD。"""
    parts = date_str.split("/")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str
