#!/usr/bin/env python3
"""根据索引文件解析 Form 4，写入 data/form4/[ticker]/[accession_no].json。

filing 级并行 + edgartools 内置限流（滑动窗口 9 req/s），无外部 limiter。
已下载的 XML 被 edgartools 永久缓存，重跑不消耗网络请求。
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from edgar import Filing, set_identity
from rich.console import Console
from rich.table import Table

console = Console()


def _safe_float(val) -> float | None:
    """安全转 float，跳过脚注引用（如 '[F1]'）和 numpy 类型。"""
    if val is None:
        return None
    s = str(val).strip()
    if s.startswith("[") or not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    """安全转 int，处理 numpy int64 等类型。"""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _write_intermediate_log(
    run_start: datetime,
    done: int,
    ok: int,
    fail: int,
    txn: int,
    error_types: dict[str, int],
) -> None:
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = run_start.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"parse_us_form4_{ts}_partial.json"
    log_path.write_text(
        json.dumps(
            {
                "run_at": run_start.isoformat(),
                "progress": {"done": done, "ok": ok, "fail": fail, "txn": txn},
                "error_distribution": dict(
                    sorted(error_types.items(), key=lambda x: -x[1])[:10]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


# ── 提取逻辑 ──


def extract_filing(filing, summary, form, ticker: str) -> dict:
    """提取 filing 级字段（含 summary 计算字段）。"""
    issuer = form.issuer
    return {
        "accession_no": filing.accession_no,
        "ticker": ticker,
        "cik": str(issuer.cik) if issuer else filing.cik,
        "company_name": str(issuer.name) if issuer else str(filing.company),
        "insider_name": summary.insider_name or "",
        "position": summary.position or "",
        "issuer": str(issuer.name) if issuer else "",
        "filing_date": str(filing.filing_date) if filing.filing_date else None,
        "reporting_period": str(form.reporting_period)
        if form.reporting_period
        else None,
        "xml_url": filing.filing_url or "",
        "index_url": filing.url or "",
        "is_10b5_1": bool(form.aff10b5_one),
        "no_securities": bool(form.no_securities),
        "remarks": form.remarks or "",
        "primary_activity": summary.primary_activity or "",
        "net_change": _safe_int(summary.net_change),
        "net_value": _safe_float(summary.net_value),
        "remaining_shares": _safe_float(summary.remaining_shares),
    }


def _extract_transaction_dates(form) -> dict[tuple[str, int], str]:
    """按 DataFrame 索引提取交易日期，返回 {(security_type, df_index): date}。"""
    dates: dict[tuple[str, int], str] = {}
    try:
        ndt = form.non_derivative_table
        if ndt and ndt.has_transactions:
            mt = ndt.market_trades
            if mt is not None and not mt.empty:
                for idx, row in mt.iterrows():
                    dates[("non-derivative", idx)] = str(row.get("Date", "")) if row.get("Date") else ""
            nmt = ndt.non_market_trades
            if nmt is not None and not nmt.empty:
                for idx, row in nmt.iterrows():
                    dates[("non-derivative", idx)] = str(row.get("Date", "")) if row.get("Date") else ""
    except Exception:
        pass
    try:
        dt = form.derivative_table
        if dt and dt.has_transactions:
            df = dt.transactions.data
            if not df.empty:
                for idx, row in df.iterrows():
                    dates[("derivative", idx)] = str(row.get("Date", "")) if row.get("Date") else ""
    except Exception:
        pass
    return dates


def extract_transactions(summary, form, accession_no: str) -> list[dict]:
    """提取所有 transaction 行。"""
    date_map = _extract_transaction_dates(form)
    # 按 get_transaction_activities() 的顺序构建索引列表
    date_keys: list[tuple[str, int]] = []
    try:
        ndt = form.non_derivative_table
        if ndt and ndt.has_transactions:
            mt = ndt.market_trades
            if mt is not None and not mt.empty:
                date_keys.extend(("non-derivative", idx) for idx in mt.index)
            nmt = ndt.non_market_trades
            if nmt is not None and not nmt.empty:
                date_keys.extend(("non-derivative", idx) for idx in nmt.index)
    except Exception:
        pass
    try:
        dt = form.derivative_table
        if dt and dt.has_transactions:
            df = dt.transactions.data
            if not df.empty:
                date_keys.extend(("derivative", idx) for idx in df.index)
    except Exception:
        pass

    rows: list[dict] = []
    for seq, a in enumerate(summary.transactions):
        txn_date = ""
        if seq < len(date_keys):
            txn_date = date_map.get(date_keys[seq], "")
        rows.append(
            {
                "accession_no": accession_no,
                "seq": seq,
                "transaction_date": txn_date or None,
                "transaction_type": a.transaction_type or "",
                "code": a.code or "",
                "code_description": a.code_description or "",
                "security_type": a.security_type or "",
                "security_title": a.security_title or "",
                "underlying_security": a.underlying_security or "",
                "shares": _safe_float(a.shares),
                "price_per_share": _safe_float(a.price_per_share),
                "value": _safe_float(a.value),
                "exercise_date": str(a.exercise_date)
                if a.exercise_date and not str(a.exercise_date).startswith("[")
                else None,
                "expiration_date": str(a.expiration_date)
                if a.expiration_date and not str(a.expiration_date).startswith("[")
                else None,
                "style": a.style
                if a.style
                not in ("white", "yellow", "red", "green", "cyan", "magenta", "blue")
                else "",
                "is_10b5_1_plan": bool(a.is_10b5_1_plan),
                "footnote_ids": a.footnote_ids or "",
                "footnotes_text": a.footnotes_text or "",
            }
        )
    return rows


# ── 任务结构 ──


@dataclass
class FilingTask:
    ticker: str
    accession_no: str
    filing_date: str
    form: str
    cik: str
    company_name: str


@dataclass
class ParseResult:
    ok: bool = False
    ticker: str = ""
    accession_no: str = ""
    transaction_count: int = 0
    error_msg: str = ""


def parse_one_filing(task: FilingTask, data_dir: Path) -> ParseResult:
    """解析单个 filing，写入 JSON。"""
    result = ParseResult(ticker=task.ticker, accession_no=task.accession_no)
    out_path = data_dir / "tickers" / task.ticker / f"{task.accession_no}.json"

    if out_path.exists():
        result.ok = True
        return result

    try:
        filing = Filing(
            cik=int(task.cik),
            company=task.company_name,
            form=task.form,
            filing_date=task.filing_date,
            accession_no=task.accession_no,
        )
        form = filing.obj()
        if form is None:
            result.error_msg = "obj() returned None (XML unavailable)"
            return result
        summary = form.get_ownership_summary()  # type: ignore[union-attr]
        filing_row = extract_filing(filing, summary, form, task.ticker)
        txn_rows = extract_transactions(summary, form, task.accession_no)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "accession_no": task.accession_no,
                    "ticker": task.ticker,
                    "filing": filing_row,
                    "transactions": txn_rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        result.transaction_count = len(txn_rows)
        result.ok = True
    except Exception as e:
        result.error_msg = str(e)

    return result


def load_index(index_dir: Path, ticker: str) -> list[FilingTask]:
    """读取索引文件，返回 FilingTask 列表。"""
    index_path = index_dir / f"{ticker}.json"
    if not index_path.exists():
        return []
    try:
        data = json.loads(index_path.read_text())
        tasks: list[FilingTask] = []
        for f in data.get("filings", []):
            tasks.append(
                FilingTask(
                    ticker=ticker,
                    accession_no=f["accession_no"],
                    filing_date=f.get("filing_date") or "",
                    form=f.get("form") or "4",
                    cik=f.get("cik") or "",
                    company_name=f.get("company_name") or "",
                )
            )
        return tasks
    except (json.JSONDecodeError, KeyError):
        return []


def run(args: argparse.Namespace) -> None:
    set_identity("Finsco support@finsco.io")

    data_dir = Path(args.data_dir)
    index_dir = data_dir / "_index"

    if not index_dir.exists():
        console.print(f"  索引目录不存在: {index_dir}")
        console.print("  请先运行 fetch-us-form4-index")
        return

    # 收集索引文件
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        index_files = [index_dir / f"{t}.json" for t in tickers]
        index_files = [f for f in index_files if f.exists()]
    else:
        index_files = sorted(index_dir.glob("US.*.json"))

    if not index_files:
        console.print("  无索引文件")
        return

    # 加载所有任务并过滤已存在
    all_tasks: list[FilingTask] = []
    skipped_by_ticker: dict[str, int] = {}
    for idx_path in index_files:
        ticker = idx_path.stem
        tasks = load_index(index_dir, ticker)
        skip = 0
        pending: list[FilingTask] = []
        for t in tasks:
            out_path = data_dir / "tickers" / t.ticker / f"{t.accession_no}.json"
            if out_path.exists():
                skip += 1
            else:
                pending.append(t)
        skipped_by_ticker[ticker] = skip
        all_tasks.extend(pending)

    total_tickers = len(index_files)
    total_skipped = sum(skipped_by_ticker.values())
    total_pending = len(all_tasks)

    console.print(
        f"  索引 ticker: {total_tickers}  "
        f"已有(跳过): {total_skipped:,}  "
        f"待解析: {total_pending:,}  "
        f"并发: {args.workers}"
    )

    if total_pending == 0:
        console.print("  全部已解析，无需处理")
        return

    run_start = datetime.now()
    start_time = time.time()

    success_count = 0
    fail_count = 0
    total_txn = 0
    errors: list[dict] = []
    error_types: dict[str, int] = {}
    first_new_printed = False

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(parse_one_filing, task, data_dir): task for task in all_tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
            except Exception as e:
                result = ParseResult(
                    ticker=task.ticker,
                    accession_no=task.accession_no,
                    error_msg=str(e),
                )

            if result.ok:
                success_count += 1
                total_txn += result.transaction_count
                if not first_new_printed:
                    first_new_printed = True
                    console.print(
                        f"  首个新文件完成: {task.ticker}/{task.accession_no}"
                    )
            else:
                fail_count += 1
                errors.append(
                    {
                        "ticker": result.ticker,
                        "accession_no": result.accession_no,
                        "error": result.error_msg,
                    }
                )
                err_key = result.error_msg[:80]
                error_types[err_key] = error_types.get(err_key, 0) + 1

            done = success_count + fail_count
            if done % 5 == 0 or done == total_pending:
                console.print(
                    f"  进度: {done}/{total_pending} "
                    f"(ok={success_count} fail={fail_count} txn={total_txn:,})"
                )
            if done % 100 == 0:
                _write_intermediate_log(
                    run_start, done, success_count, fail_count, total_txn, error_types
                )

    elapsed = time.time() - start_time

    summary = Table(title="解析完成", show_header=True, header_style="bold", box=None)
    summary.add_column("项目", style="bold")
    summary.add_column("值")
    summary.add_row("ticker 数", f"{total_tickers:,}")
    summary.add_row("已有(跳过)", f"{total_skipped:,}")
    summary.add_row("新解析", f"{success_count:,}")
    summary.add_row("失败", f"{fail_count:,}")
    summary.add_row("总 transactions", f"{total_txn:,}")
    summary.add_row("耗时", f"{elapsed / 60:.1f} 分钟")
    console.print()
    console.print(summary)

    if error_types and not args.quiet:
        dist_table = Table(
            title="错误分布 (Top 10)", show_header=True, header_style="bold yellow", box=None
        )
        dist_table.add_column("错误类型", max_width=60)
        dist_table.add_column("数量", justify="right")
        for err_key, count in sorted(error_types.items(), key=lambda x: -x[1])[:10]:
            dist_table.add_row(err_key, f"{count:,}")
        console.print()
        console.print(dist_table)

    if errors and not args.quiet:
        err_table = Table(
            title="错误列表", show_header=True, header_style="bold red", box=None
        )
        err_table.add_column("Filing")
        err_table.add_column("Error")
        for e in errors[:20]:
            err_table.add_row(f"{e['ticker']}/{e['accession_no']}", e["error"][:60])
        if len(errors) > 20:
            err_table.add_row("...", f"共 {len(errors)} 个错误")
        console.print()
        console.print(err_table)

    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = run_start.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"parse_us_form4_{ts}.json"
    log_path.write_text(
        json.dumps(
            {
                "run_at": run_start.isoformat(),
                "elapsed_seconds": round(elapsed, 1),
                "summary": {
                    "tickers": total_tickers,
                    "skipped": total_skipped,
                    "parsed": success_count,
                    "failed": fail_count,
                    "transactions": total_txn,
                },
                "error_distribution": dict(
                    sorted(error_types.items(), key=lambda x: -x[1])[:20]
                ),
                "errors": errors[:50],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    console.print(f"\n  日志已写入: {log_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="根据索引解析 Form 4 内部人交易数据（filing 级并行）"
    )
    p.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="逗号分隔的 ticker 列表（US.XXX 格式，默认解析全部索引）",
    )
    p.add_argument(
        "--workers", type=int, default=4, help="并发线程数 (默认 4, 最大 20)"
    )
    p.add_argument(
        "--data-dir", type=str, default="data/form4", help="数据目录 (默认 data/form4/)"
    )
    p.add_argument("--quiet", action="store_true", help="cron 模式")
    args = p.parse_args()
    if args.workers < 1 or args.workers > 20:
        p.error("--workers 范围 1-20")
    return args


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
