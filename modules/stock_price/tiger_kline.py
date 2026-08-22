"""Tiger Open API 日K线数据获取。

封装 Tiger SDK 的 get_bars_by_page，自动分页 + 重试。
"""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Any

from tigeropen.common.consts import BarPeriod, QuoteRight
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.tiger_open_config import TigerOpenClientConfig


def _create_quote_client(config_path: str | None = None) -> QuoteClient:
    """创建 QuoteClient，配置文件路径优先级：参数 > 环境变量 > 当前目录。"""
    props_path = config_path or os.environ.get("TIGEROPEN_PROPS_PATH")
    if props_path:
        config = TigerOpenClientConfig(props_path=props_path)
    else:
        config = TigerOpenClientConfig()
    return QuoteClient(client_config=config)


class TigerKlineFetcher:
    """Tiger API 日K线数据获取，自动分页 + 重试。

    SDK 的 get_bars_by_page 内置 time_interval 节流，无需额外限流。

    用法::

        fetcher = TigerKlineFetcher()
        records = fetcher.fetch_daily("00700", date(2024, 1, 1), date(2024, 12, 31), QuoteRight.NR)
    """

    def __init__(
        self, client: QuoteClient | None = None, config_path: str | None = None
    ) -> None:
        self._client = client or _create_quote_client(config_path)

    def fetch_daily(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        right: QuoteRight = QuoteRight.NR,
        max_retries: int = 3,
    ) -> list[dict[str, Any]]:
        """获取单个标的的日K线数据，自动分页。

        Args:
            symbol: 股票代码，如 "00700"
            start_date: 起始日期
            end_date: 结束日期
            right: 复权方式 QuoteRight.NR(不复权) / QuoteRight.BR(前复权)
            max_retries: 最大重试次数

        Returns:
            [{"trade_date", "open", "high", "low", "close", "volume", "turnover"}, ...]
        """
        for attempt in range(max_retries):
            try:
                bars = self._client.get_bars_by_page(
                    symbol=symbol,
                    period=BarPeriod.DAY,
                    begin_time=start_date.strftime("%Y-%m-%d"),
                    end_time=end_date.strftime("%Y-%m-%d"),
                    right=right,
                    page_size=1000,
                    time_interval=1,
                )
                if bars is None or bars.empty:
                    return []

                records: list[dict[str, Any]] = []
                for _, row in bars.iterrows():
                    ts = row.get("time")
                    if ts is not None:
                        trade_date = (
                            date.fromtimestamp(ts / 1000)
                            if ts > 1e12
                            else date.fromtimestamp(ts)
                        )
                    else:
                        trade_date = start_date

                    records.append(
                        {
                            "trade_date": trade_date.isoformat(),
                            "open": float(row.get("open", 0)),
                            "high": float(row.get("high", 0)),
                            "low": float(row.get("low", 0)),
                            "close": float(row.get("close", 0)),
                            "volume": int(row.get("volume", 0)),
                            "turnover": float(row.get("amount", 0)),
                        }
                    )
                return records

            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"获取 {symbol} K线失败（{right.value}），已重试 {max_retries} 次: {e}"
                    ) from e

        return []
