-- ============================================================
-- MFSES v2 Migration — Add new columns for updated formulas
-- ============================================================
-- Run this in Supabase SQL Editor AFTER the initial schema
-- ============================================================

-- Add new columns to stock_raw_data
ALTER TABLE stock_raw_data
ADD COLUMN IF NOT EXISTS analyst_rating NUMERIC(3,2),
ADD COLUMN IF NOT EXISTS short_interest_pct NUMERIC(8,4),
ADD COLUMN IF NOT EXISTS obv_trend NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS obv_price_divergence NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS price_trend_20d NUMERIC(8,4);

-- Add comments
COMMENT ON COLUMN stock_raw_data.analyst_rating IS 'Analyst consensus rating 1-5 (1=strong sell, 5=strong buy)';
COMMENT ON COLUMN stock_raw_data.short_interest_pct IS 'Short interest as % of float';
COMMENT ON COLUMN stock_raw_data.obv_trend IS 'On-Balance Volume trend % over 20 days';
COMMENT ON COLUMN stock_raw_data.obv_price_divergence IS 'OBV trend minus price trend (positive = bullish divergence)';
COMMENT ON COLUMN stock_raw_data.price_trend_20d IS 'Price trend % over 20 days';

-- Drop and recreate view (column order changed, can't just replace)
DROP VIEW IF EXISTS dashboard_stocks;
CREATE OR REPLACE VIEW dashboard_stocks AS
SELECT
    t.ticker,
    t.company_name,
    t.sector,
    t.industry,
    t.tier,

    -- Current price & market data
    r.price,
    r.price_change_pct,
    r.volume,
    r.volume_ratio,
    r.market_cap,

    -- 6 Factor Scores
    s.moat_score,
    s.growth_score,
    s.balance_score,
    s.valuation_score,
    s.sentiment_score,
    s.dividend_score,
    s.total_score,

    -- Composites
    s.mfses_short,
    s.mfses_mid,
    s.mfses_long,

    -- Graham
    s.graham_value,
    s.graham_upside_pct,

    -- Flags
    s.is_triple_crown,
    s.is_value_trap,
    s.is_expensive_growth,

    -- Dividend details
    r.annual_dividend,
    r.dividend_yield,
    r.payout_ratio,
    r.dividend_growth_5yr,
    r.consecutive_increases,
    r.ex_dividend_date,

    -- Earnings
    r.eps_current,
    r.eps_growth_rate,
    r.debt_to_equity,

    -- NEW: v2 data
    r.analyst_rating,
    r.short_interest_pct,
    r.obv_trend,
    r.obv_price_divergence,
    r.price_trend_20d,

    -- Markov state
    st.current_state AS markov_state,
    st.last_updated AS markov_last_updated,
    st.promotion_reason,

    -- Data freshness
    r.data_quality_score,
    s.scored_at,
    r.collected_at

FROM tickers t
LEFT JOIN stock_scores s ON t.ticker = s.ticker
LEFT JOIN stock_raw_data r ON t.ticker = r.ticker
LEFT JOIN stock_states st ON t.ticker = st.ticker
WHERE t.is_active = true;

-- Done!
SELECT 'MFSES v2 migration complete!' AS status;
