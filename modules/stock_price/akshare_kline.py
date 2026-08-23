"""AKShare 日K线数据获取。

通过 akshare 库（新浪财经数据源）获取港股日K线数据，无需 API Key。
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, ClassVar


class AkshareKlineFetcher:
    """AKShare 港股日K线数据获取（新浪财经数据源）。

    用法::

        fetcher = AkshareKlineFetcher()
        records = fetcher.fetch_daily("00700", date(2024, 1, 1), date(2024, 12, 31), "NR")
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
        """获取单个港股标的的日K线数据。

        Args:
            symbol: 股票代码，如 "00700"
            start_date: 起始日期
            end_date: 结束日期
            right: 复权方式 "NR"(不复权) / "BR"(前复权)
            max_retries: 最大重试次数

        Returns:
            [{"trade_date", "open", "high", "low", "close", "volume", "turnover"}, ...]
        """
        import akshare as ak

        adjust = self._ADJUST_MAP.get(right.upper(), "")

        for attempt in range(max_retries):
            try:
                df = ak.stock_hk_daily(symbol=symbol, adjust=adjust)

                if df is None or df.empty:
                    return []

                # stock_hk_daily 返回全量数据，按日期过滤
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
                    wait = 2 ** (attempt + 1)
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"AKShare 获取 {symbol} K线失败（{right}），已重试 {max_retries} 次: {e}"
                    ) from e

        return []
