-- Migration V3: Chart data cache table
-- Caches Polygon API responses to reduce API calls (5/min free tier)

CREATE TABLE IF NOT EXISTS stock_financials_cache (
    ticker TEXT PRIMARY KEY,
    income_data JSONB,        -- Array of annual income statements
    cashflow_data JSONB,      -- Array of annual cash flow statements
    balance_data JSONB,       -- Array of annual balance sheet data
    price_bars JSONB,         -- Array of daily OHLCV bars (2 years)
    cached_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days')
);

-- Index for cache expiry lookups
CREATE INDEX IF NOT EXISTS idx_sfc_expires ON stock_financials_cache(expires_at);

-- Enable RLS but allow anon reads (same as other tables)
ALTER TABLE stock_financials_cache ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow anon read" ON stock_financials_cache
    FOR SELECT USING (true);

CREATE POLICY "Allow anon insert" ON stock_financials_cache
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow anon update" ON stock_financials_cache
    FOR UPDATE USING (true);

-- Cleanup function (optional, run via cron)
-- DELETE FROM stock_financials_cache WHERE expires_at < NOW();
