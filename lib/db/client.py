"""Supabase 客户端初始化。"""

from __future__ import annotations

import os

from supabase import ClientOptions, create_client

_url = os.environ["SUPABASE_URL"]
_key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
_meta_client = create_client(_url, _key, ClientOptions(schema="meta_data"))
_md_client = create_client(_url, _key, ClientOptions(schema="market_data"))
