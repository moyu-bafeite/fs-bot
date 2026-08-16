-- Form 4 内部人交易数据表
-- 在 Supabase SQL editor 中执行

CREATE SCHEMA IF NOT EXISTS market_data;

-- 暴露 schema 给 PostgREST（Supabase 客户端必需）
GRANT USAGE ON SCHEMA market_data TO anon, authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA market_data TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA market_data GRANT ALL ON TABLES TO anon, authenticated;

-- 1. filing 级表
CREATE TABLE IF NOT EXISTS market_data.us_sec_form4_filings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    accession_no text NOT NULL UNIQUE,
    ticker text NOT NULL,
    cik text,
    company_name text,
    insider_name text,
    position text,
    issuer text,
    filing_date date,
    reporting_period date,
    xml_url text,
    index_url text,
    is_10b5_1 boolean,
    no_securities boolean,
    remarks text,
    primary_activity text,
    net_change numeric,
    net_value numeric,
    remaining_shares numeric,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_form4_filings_ticker ON market_data.us_sec_form4_filings (ticker);
CREATE INDEX IF NOT EXISTS idx_form4_filings_filing_date ON market_data.us_sec_form4_filings (filing_date);
CREATE INDEX IF NOT EXISTS idx_form4_filings_reporting_period ON market_data.us_sec_form4_filings (reporting_period);

-- 2. transaction 级表
CREATE TABLE IF NOT EXISTS market_data.us_sec_form4_filing_transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    accession_no text NOT NULL,
    seq int NOT NULL,
    transaction_date date,
    transaction_type text NOT NULL,
    code text NOT NULL,
    code_description text,
    security_type text NOT NULL,
    security_title text,
    underlying_security text,
    shares numeric,
    price_per_share numeric,
    value numeric,
    exercise_date date,
    expiration_date date,
    style text,
    is_10b5_1_plan boolean,
    footnote_ids text,
    footnotes_text text,
    UNIQUE (accession_no, seq)
);

CREATE INDEX IF NOT EXISTS idx_form4_txn_accession ON market_data.us_sec_form4_filing_transactions (accession_no);
CREATE INDEX IF NOT EXISTS idx_form4_txn_type_code ON market_data.us_sec_form4_filing_transactions (transaction_type, code, security_type);

-- 3. 交易类型定义表
CREATE TABLE IF NOT EXISTS market_data.us_sec_form4_transaction_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_type text NOT NULL,
    code text NOT NULL,
    security_type text NOT NULL,
    code_description text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (transaction_type, code, security_type)
);
