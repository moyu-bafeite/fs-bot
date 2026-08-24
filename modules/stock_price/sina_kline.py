"""新浪财经实时行情 + 历史日K线数据获取。

实时数据来源: hq.sinajs.cn（收盘后立即更新，无 MiniRacer 依赖）
历史数据来源: akshare stock_hk_daily（新浪历史接口）
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any, ClassVar

import httpx

_SINA_RT_URL = "https://hq.sinajs.cn/list=rt_hk{code}"
_BATCH_SIZE = 20

# rt_hk 响应格式:
# 英文名,中文名,昨收,今开,最高,最低,最新价,涨跌额,涨跌幅,买入,卖出,
# 成交额,成交量,换手率,市盈率,总市值,流通市值,日期,时间,...
_RT_FIELDS = re.compile(
    r'"(.+?)"'
)


class SinaRealtimeFetcher:
    """新浪财经实时行情 + 历史日K线。

    实时数据收盘后立即可用，适合 16:30 开始的 ETL 流程。

    用法::

        fetcher = SinaRealtimeFetcher()
        records = fetcher.fetch_daily("00700", date(2024, 1, 1), date.today(), "NR")
    """

    _ADJUST_MAP: ClassVar[dict[str, str]] = {
        "NR": "",
        "BR": "qfq",
    }

    def fetch_daily(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        right: str = "NR",
        max_retries: int = 3,
    ) -> list[dict[str, Any]]:
        """获取港股日K线数据。

        当 end_date 为今天时，使用实时行情 API（收盘后立即可用）；
        否则回退到历史日K线 API。

        Args:
            symbol: 股票代码，如 "00700"
            start_date: 起始日期
            end_date: 结束日期
            right: 复权方式 "NR" / "BR"
            max_retries: 最大重试次数

        Returns:
            [{"trade_date", "open", "high", "low", "close", "volume", "turnover"}, ...]
        """
        today = date.today()

        if end_date >= today:
            # 实时数据：只覆盖今天
            rt_records = self._fetch_realtime(symbol, max_retries)
            # 历史数据：start_date ~ yesterday
            if start_date < today:
                hist_records = self._fetch_history(
                    symbol, start_date, today, right, max_retries
                )
            else:
                hist_records = []
            # 合并，实时数据优先（覆盖今天的记录）
            return self._merge(rt_records, hist_records)
        else:
            return self._fetch_history(symbol, start_date, end_date, right, max_retries)

    def _fetch_realtime(
        self, symbol: str, max_retries: int
    ) -> list[dict[str, Any]]:
        """从新浪实时行情 API 获取今日数据。"""
        url = _SINA_RT_URL.format(code=symbol)

        for attempt in range(max_retries):
            try:
                resp = httpx.get(url, timeout=10, headers={"Referer": "https://finance.sina.com.cn/"})
                resp.raise_for_status()
                return self._parse_rt_response(symbol, resp.text)
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                else:
                    raise RuntimeError(
                        f"新浪实时行情获取 {symbol} 失败，已重试 {max_retries} 次: {e}"
                    ) from e
        return []

    def _parse_rt_response(
        self, symbol: str, text: str
    ) -> list[dict[str, Any]]:
        """解析新浪实时行情响应。"""
        match = _RT_FIELDS.search(text)
        if not match:
            return []

        fields = match.group(1).split(",")
        if len(fields) < 18:
            return []

        # 字段索引:
        # 0:英文名 1:中文名 2:昨收 3:今开 4:最高 5:最低 6:最新价
        # 7:涨跌额 8:涨跌幅 9:买入 10:卖出 11:成交额 12:成交量
        # ...
        # 17:日期 (YYYY/MM/DD) 18:时间 (HH:MM:SS)
        trade_date_str = fields[17].replace("/", "-")

        try:
            open_price = float(fields[3])
            high_price = float(fields[4])
            low_price = float(fields[5])
            close_price = float(fields[6])
            volume = int(float(fields[12]))
            turnover = float(fields[11])
        except (ValueError, IndexError):
            return []

        # 跳过停牌/无数据的股票
        if close_price == 0:
            return []

        return [
            {
                "trade_date": trade_date_str,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "turnover": turnover,
            }
        ]

    def _fetch_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        right: str,
        max_retries: int,
    ) -> list[dict[str, Any]]:
        """从 AKShare 历史接口获取数据。"""
        import akshare as ak

        adjust = self._ADJUST_MAP.get(right.upper(), "")

        for attempt in range(max_retries):
            try:
                df = ak.stock_hk_daily(symbol=symbol, adjust=adjust)
                if df is None or df.empty:
                    return []

                df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
                if df.empty:
                    return []

                records: list[dict[str, Any]] = []
                for _, row in df.iterrows():
                    trade_date = row["date"]
                    trade_date_str = (
                        trade_date.strftime("%Y-%m-%d")
                        if hasattr(trade_date, "strftime")
                        else str(trade_date)
                    )
                    records.append(
                        {
                            "trade_date": trade_date_str,
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": int(row["volume"]),
                            "turnover": float(row["amount"]),
                        }
                    )
                return records

            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                else:
                    raise RuntimeError(
                        f"AKShare 获取 {symbol} 历史K线失败（{right}），已重试 {max_retries} 次: {e}"
                    ) from e

        return []

    @staticmethod
    def _merge(
        realtime: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """合并实时和历史数据，实时优先（按日期去重）。"""
        seen: dict[str, dict[str, Any]] = {}
        for rec in history:
            seen[rec["trade_date"]] = rec
        for rec in realtime:
            seen[rec["trade_date"]] = rec
        return sorted(seen.values(), key=lambda r: r["trade_date"])
