"""Supabase Postgres 操作：meta_data / market_data。

按领域拆分为子模块，此处统一 re-export 保持向后兼容。
"""

from lib.db.client import _md_client, _meta_client
from lib.db.daily_prices import (
    get_max_trade_dates,
    get_nr_daily_turnover,
    get_nr_daily_turnovers,
    upsert_br_daily_prices,
    upsert_nr_daily_prices,
)
from lib.db.repurchase_announcements import (
    get_existing_urls,
    get_unparsed_announcements,
    mark_announcement_parsed,
    upsert_repurchase_announcements,
)
from lib.db.repurchase_realtime import (
    get_latest_unnotified_realtime_report,
    get_realtime_report_keys,
    get_realtime_reports_by_stock,
    get_repurchase_realtime_reports_by_trade_date,
    get_unnotified_realtime_reports_by_stock,
    insert_realtime_reports,
    mark_realtime_reports_notified,
)
from lib.db.repurchase_reports import (
    get_repurchase_reports_by_trade_date,
    upsert_repurchase_reports,
)
from lib.db.stocks import (
    HK_STOCKS_TABLE,
    get_hk_stock_by_code,
    get_hk_stocks,
    get_stock_names,
    upsert_stocks,
)

__all__ = [
    "_md_client",
    "_meta_client",
    "HK_STOCKS_TABLE",
    "get_hk_stocks",
    "get_hk_stock_by_code",
    "get_stock_names",
    "upsert_stocks",
    "get_repurchase_reports_by_trade_date",
    "upsert_repurchase_reports",
    "upsert_br_daily_prices",
    "upsert_nr_daily_prices",
    "get_nr_daily_turnover",
    "get_nr_daily_turnovers",
    "get_max_trade_dates",
    "upsert_repurchase_announcements",
    "get_existing_urls",
    "get_unparsed_announcements",
    "mark_announcement_parsed",
    "get_realtime_report_keys",
    "insert_realtime_reports",
    "get_repurchase_realtime_reports_by_trade_date",
    "get_realtime_reports_by_stock",
    "get_unnotified_realtime_reports_by_stock",
    "get_latest_unnotified_realtime_report",
    "mark_realtime_reports_notified",
]
