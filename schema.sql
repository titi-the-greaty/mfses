-- ============================================================
-- SeeSaw MFSES v5.1 — Supabase PostgreSQL Schema
-- ============================================================
-- Run this in Supabase SQL Editor (supabase.com → your project → SQL Editor)
-- Or via CLI: supabase db push
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ============================================================
-- TABLE 1: tickers (Master list — 2,501 stocks)
-- ============================================================
-- The universe of stocks we track. Loaded once during bootstrap.
-- Tier determines default update priority.

CREATE TABLE IF NOT EXISTS tickers (
    ticker          TEXT PRIMARY KEY,
    company_name    TEXT NOT NULL,
    sector          TEXT NOT NULL DEFAULT 'Unknown',
    industry        TEXT,
    tier            SMALLINT NOT NULL DEFAULT 3,  -- 1=Mega, 2=Large, 3=Mid, 4=Small
    market_cap      BIGINT,                       -- Latest known market cap in USD
    is_active       BOOLEAN NOT NULL DEFAULT true, -- Set false to stop tracking
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    CONSTRAINT valid_tier CHECK (tier BETWEEN 1 AND 4)
);

COMMENT ON TABLE tickers IS 'Master list of 2,501 tracked stocks with sector and tier classification';
COMMENT ON COLUMN tickers.tier IS '1=Mega ($100B+), 2=Large ($10B-100B), 3=Mid ($2B-10B), 4=Small ($300M-2B)';


-- ============================================================
-- TABLE 2: stock_states (Markov state machine)
-- ============================================================
-- Tracks the current Markov state for each ticker.
-- The prioritizer reads this to decide what to fetch each cycle.

CREATE TABLE IF NOT EXISTS stock_states (
    ticker              TEXT PRIMARY KEY REFERENCES tickers(ticker) ON DELETE CASCADE,
    current_state       TEXT NOT NULL DEFAULT 'COLD',
    previous_state      TEXT,
    last_updated        TIMESTAMPTZ NOT NULL DEFAULT now(),
    next_update_due     TIMESTAMPTZ NOT NULL DEFAULT now(),
    promotion_reason    TEXT,          -- Why it was promoted (e.g., "volume_spike_3x")
    promotion_expires   TIMESTAMPTZ,   -- When forced promotion expires (24hr max)
    consecutive_hot     SMALLINT NOT NULL DEFAULT 0,  -- How many cycles it's been HOT
    
    CONSTRAINT valid_state CHECK (current_state IN ('HOT', 'WARM', 'COLD', 'FROZEN'))
);

COMMENT ON TABLE stock_states IS 'Markov state machine — determines update frequency per ticker';
COMMENT ON COLUMN stock_states.next_update_due IS 'Prioritizer selects tickers where now() >= next_update_due';


-- ============================================================
-- TABLE 3: stock_raw_data (Raw API data from collector)
-- ============================================================
-- The collector writes here. The scorer reads from here.
-- One row per ticker, updated in place each cycle.

CREATE TABLE IF NOT EXISTS stock_raw_data (
    ticker                  TEXT PRIMARY KEY REFERENCES tickers(ticker) ON DELETE CASCADE,
    
    -- Price & Volume
    price                   NUMERIC(12,4),
    previous_close          NUMERIC(12,4),
    price_change_pct        NUMERIC(8,4),       -- Daily % change
    volume                  BIGINT,
    avg_volume_20d          BIGINT,
    volume_ratio            NUMERIC(6,3),       -- volume / avg_volume_20d
    
    -- Market Data
    market_cap              BIGINT,
    shares_outstanding      BIGINT,
    fifty_two_week_high     NUMERIC(12,4),
    fifty_two_week_low      NUMERIC(12,4),
    
    -- Earnings
    eps_current             NUMERIC(10,4),      -- Latest annual EPS
    eps_1y_ago              NUMERIC(10,4),      -- EPS from 1 year ago
    eps_growth_rate         NUMERIC(8,4),       -- YoY growth %
    
    -- Balance Sheet
    total_debt              BIGINT,
    shareholders_equity     BIGINT,
    debt_to_equity          NUMERIC(8,4),
    
    -- Dividends
    annual_dividend         NUMERIC(10,4),      -- Annual dividend per share
    dividend_yield          NUMERIC(8,4),       -- Yield %
    payout_ratio            NUMERIC(8,4),       -- Payout ratio %
    dividend_growth_5yr     NUMERIC(8,4),       -- 5-year dividend growth rate %
    consecutive_increases   SMALLINT DEFAULT 0, -- Years of consecutive dividend increases
    ex_dividend_date        DATE,
    
    -- News / Sentiment (for future NewsIQ)
    news_count_1h           SMALLINT DEFAULT 0,
    news_count_24h          SMALLINT DEFAULT 0,
    
    -- Metadata
    data_quality_score      SMALLINT DEFAULT 0, -- 0-100 quality metric
    last_price_update       TIMESTAMPTZ,
    last_fundamental_update TIMESTAMPTZ,
    last_dividend_update    TIMESTAMPTZ,
    collected_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE stock_raw_data IS 'Raw market data from Polygon API — written by collector, read by scorer';


-- ============================================================
-- TABLE 4: stock_scores (MFSES calculated scores)
-- ============================================================
-- The scorer writes here. The dashboard reads from here.
-- This is the main table the frontend queries.

CREATE TABLE IF NOT EXISTS stock_scores (
    ticker              TEXT PRIMARY KEY REFERENCES tickers(ticker) ON DELETE CASCADE,
    
    -- The 6 Factor Scores (0-20 each)
    moat_score          SMALLINT NOT NULL DEFAULT 0,
    growth_score        SMALLINT NOT NULL DEFAULT 0,
    balance_score       SMALLINT NOT NULL DEFAULT 0,
    valuation_score     SMALLINT NOT NULL DEFAULT 0,
    sentiment_score     SMALLINT NOT NULL DEFAULT 12,  -- Neutral default
    dividend_score      SMALLINT NOT NULL DEFAULT 0,
    
    -- Total raw score (sum of 6 factors, max 120)
    total_score         SMALLINT GENERATED ALWAYS AS (
        moat_score + growth_score + balance_score + 
        valuation_score + sentiment_score + dividend_score
    ) STORED,
    
    -- Time Horizon Composites (0.0 - 20.0)
    mfses_short         NUMERIC(5,2) NOT NULL DEFAULT 0,   -- 0-6 month
    mfses_mid           NUMERIC(5,2) NOT NULL DEFAULT 0,   -- 2-3 year
    mfses_long          NUMERIC(5,2) NOT NULL DEFAULT 0,   -- 5+ year
    
    -- Graham Valuation
    graham_value        NUMERIC(12,4),          -- Intrinsic value per share
    graham_upside_pct   NUMERIC(8,2),           -- % upside/downside vs price
    
    -- Flags
    is_triple_crown     BOOLEAN GENERATED ALWAYS AS (
        mfses_short >= 14 AND mfses_mid >= 14 AND mfses_long >= 14
    ) STORED,
    is_value_trap       BOOLEAN GENERATED ALWAYS AS (
        valuation_score >= 18 AND (moat_score < 12 OR balance_score < 10)
    ) STORED,
    is_expensive_growth BOOLEAN GENERATED ALWAYS AS (
        growth_score >= 18 AND valuation_score < 8
    ) STORED,
    
    -- Metadata
    scored_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Constraints
    CONSTRAINT valid_moat CHECK (moat_score BETWEEN 0 AND 20),
    CONSTRAINT valid_growth CHECK (growth_score BETWEEN 0 AND 20),
    CONSTRAINT valid_balance CHECK (balance_score BETWEEN 0 AND 20),
    CONSTRAINT valid_valuation CHECK (valuation_score BETWEEN 0 AND 20),
    CONSTRAINT valid_sentiment CHECK (sentiment_score BETWEEN 0 AND 20),
    CONSTRAINT valid_dividend CHECK (dividend_score BETWEEN 0 AND 20)
);

COMMENT ON TABLE stock_scores IS 'Calculated MFSES scores — the main table the dashboard reads from';
COMMENT ON COLUMN stock_scores.mfses_short IS 'Short-term composite: growth×0.35 + val×0.20 + sent×0.15 + moat×0.15 + bal×0.10 + div×0.05';
COMMENT ON COLUMN stock_scores.mfses_mid IS 'Mid-term composite: moat×0.30 + val×0.20 + growth×0.20 + bal×0.15 + div×0.10 + sent×0.05';
COMMENT ON COLUMN stock_scores.mfses_long IS 'Long-term composite: moat×0.30 + bal×0.25 + div×0.15 + val×0.15 + growth×0.10 + sent×0.05';


-- ============================================================
-- TABLE 5: pipeline_runs (Monitoring & logging)
-- ============================================================
-- Every pipeline execution gets logged here.
-- Used for the dashboard "system health" widget and n8n alert context.

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_type            TEXT NOT NULL,          -- 'market_hours', 'daily_full', 'manual'
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_seconds    NUMERIC(8,2),
    
    -- Step results
    markov_tickers_due  INTEGER DEFAULT 0,      -- How many tickers Markov selected
    collected_count     INTEGER DEFAULT 0,      -- How many successfully collected
    scored_count        INTEGER DEFAULT 0,      -- How many successfully scored
    states_promoted     INTEGER DEFAULT 0,      -- Markov promotions this cycle
    states_demoted      INTEGER DEFAULT 0,      -- Markov demotions this cycle
    
    -- API usage
    api_calls_made      INTEGER DEFAULT 0,
    api_errors          INTEGER DEFAULT 0,
    
    -- Status
    status              TEXT NOT NULL DEFAULT 'running', -- running, success, partial, failed
    error_message       TEXT,
    error_step          TEXT,                   -- Which step failed: markov/collector/scorer/state_updater
    retry_count         SMALLINT DEFAULT 0,
    
    CONSTRAINT valid_status CHECK (status IN ('running', 'success', 'partial', 'failed'))
);

COMMENT ON TABLE pipeline_runs IS 'Execution log for every pipeline run — used for monitoring and alerts';


-- ============================================================
-- TABLE 6: score_history (Optional — for trend tracking)
-- ============================================================
-- Snapshot of scores over time. Enables "score changed +5 this week" features.
-- Only insert for tickers whose scores actually changed.

CREATE TABLE IF NOT EXISTS score_history (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker              TEXT NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Snapshot of scores at this point in time
    moat_score          SMALLINT,
    growth_score        SMALLINT,
    balance_score       SMALLINT,
    valuation_score     SMALLINT,
    sentiment_score     SMALLINT,
    dividend_score      SMALLINT,
    total_score         SMALLINT,
    mfses_short         NUMERIC(5,2),
    mfses_mid           NUMERIC(5,2),
    mfses_long          NUMERIC(5,2),
    graham_upside_pct   NUMERIC(8,2),
    price               NUMERIC(12,4)
);

COMMENT ON TABLE score_history IS 'Daily score snapshots for trend analysis (insert once per day per ticker)';


-- ============================================================
-- INDEXES — Fast queries for the dashboard and pipeline
-- ============================================================

-- Dashboard: Sort by any score column
CREATE INDEX idx_scores_short ON stock_scores (mfses_short DESC);
CREATE INDEX idx_scores_mid ON stock_scores (mfses_mid DESC);
CREATE INDEX idx_scores_long ON stock_scores (mfses_long DESC);
CREATE INDEX idx_scores_total ON stock_scores (total_score DESC);
CREATE INDEX idx_scores_graham ON stock_scores (graham_upside_pct DESC NULLS LAST);

-- Dashboard: Filter by sector
CREATE INDEX idx_tickers_sector ON tickers (sector);
CREATE INDEX idx_tickers_tier ON tickers (tier);
CREATE INDEX idx_tickers_active ON tickers (is_active) WHERE is_active = true;

-- Markov prioritizer: Find tickers due for update
CREATE INDEX idx_states_due ON stock_states (next_update_due ASC);
CREATE INDEX idx_states_state ON stock_states (current_state);

-- Pipeline monitoring: Recent runs
CREATE INDEX idx_runs_started ON pipeline_runs (started_at DESC);
CREATE INDEX idx_runs_status ON pipeline_runs (status) WHERE status = 'failed';

-- Score history: Lookup by ticker + date
CREATE INDEX idx_history_ticker_date ON score_history (ticker, recorded_at DESC);

-- Raw data: Freshness checks
CREATE INDEX idx_raw_collected ON stock_raw_data (collected_at);


-- ============================================================
-- VIEWS — Pre-joined queries for the dashboard
-- ============================================================

-- Main dashboard view: Everything the frontend needs in one query
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

COMMENT ON VIEW dashboard_stocks IS 'Pre-joined view for the dashboard — one query gets everything';


-- System health view for the dashboard widget
CREATE OR REPLACE VIEW system_health AS
SELECT
    (SELECT COUNT(*) FROM tickers WHERE is_active = true) AS total_active_tickers,
    (SELECT COUNT(*) FROM stock_states WHERE current_state = 'HOT') AS hot_count,
    (SELECT COUNT(*) FROM stock_states WHERE current_state = 'WARM') AS warm_count,
    (SELECT COUNT(*) FROM stock_states WHERE current_state = 'COLD') AS cold_count,
    (SELECT COUNT(*) FROM stock_states WHERE current_state = 'FROZEN') AS frozen_count,
    (SELECT COUNT(*) FROM stock_scores WHERE scored_at > now() - INTERVAL '1 hour') AS scored_last_hour,
    (SELECT COUNT(*) FROM stock_scores WHERE scored_at > now() - INTERVAL '24 hours') AS scored_last_24h,
    (SELECT status FROM pipeline_runs ORDER BY started_at DESC LIMIT 1) AS last_run_status,
    (SELECT started_at FROM pipeline_runs ORDER BY started_at DESC LIMIT 1) AS last_run_time,
    (SELECT SUM(api_calls_made) FROM pipeline_runs WHERE started_at > now() - INTERVAL '24 hours') AS api_calls_today;

COMMENT ON VIEW system_health IS 'Quick system status for dashboard header widget';


-- ============================================================
-- ROW LEVEL SECURITY (RLS) — Supabase best practice
-- ============================================================

-- Enable RLS on all tables
ALTER TABLE tickers ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_raw_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE score_history ENABLE ROW LEVEL SECURITY;

-- Public read access for dashboard (anon key)
CREATE POLICY "Public read tickers" ON tickers FOR SELECT USING (true);
CREATE POLICY "Public read scores" ON stock_scores FOR SELECT USING (true);
CREATE POLICY "Public read raw_data" ON stock_raw_data FOR SELECT USING (true);
CREATE POLICY "Public read states" ON stock_states FOR SELECT USING (true);
CREATE POLICY "Public read history" ON score_history FOR SELECT USING (true);
CREATE POLICY "Public read runs" ON pipeline_runs FOR SELECT USING (true);

-- Service role (Edge Functions) can do everything
CREATE POLICY "Service write tickers" ON tickers FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service write scores" ON stock_scores FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service write raw_data" ON stock_raw_data FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service write states" ON stock_states FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service write history" ON score_history FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service write runs" ON pipeline_runs FOR ALL USING (true) WITH CHECK (true);


-- ============================================================
-- FUNCTIONS — Reusable database functions
-- ============================================================

-- Function: Get tickers due for update (called by Markov prioritizer)
CREATE OR REPLACE FUNCTION get_tickers_due_for_update()
RETURNS TABLE (
    ticker TEXT,
    current_state TEXT,
    last_updated TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ss.ticker,
        ss.current_state,
        ss.last_updated
    FROM stock_states ss
    JOIN tickers t ON ss.ticker = t.ticker
    WHERE t.is_active = true
      AND ss.next_update_due <= now()
    ORDER BY 
        CASE ss.current_state
            WHEN 'HOT' THEN 1
            WHEN 'WARM' THEN 2
            WHEN 'COLD' THEN 3
            WHEN 'FROZEN' THEN 4
        END,
        ss.next_update_due ASC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_tickers_due_for_update IS 'Returns all tickers whose next_update_due has passed, ordered by priority';


-- Function: Update Markov state + set next_update_due
CREATE OR REPLACE FUNCTION update_markov_state(
    p_ticker TEXT,
    p_new_state TEXT,
    p_reason TEXT DEFAULT NULL
)
RETURNS VOID AS $$
DECLARE
    interval_minutes INTEGER;
BEGIN
    -- Determine update interval based on new state
    interval_minutes := CASE p_new_state
        WHEN 'HOT' THEN 30
        WHEN 'WARM' THEN 120
        WHEN 'COLD' THEN 360
        WHEN 'FROZEN' THEN 1440
        ELSE 360
    END;
    
    UPDATE stock_states SET
        previous_state = current_state,
        current_state = p_new_state,
        last_updated = now(),
        next_update_due = now() + (interval_minutes || ' minutes')::INTERVAL,
        promotion_reason = CASE 
            WHEN p_new_state IN ('HOT', 'WARM') THEN p_reason 
            ELSE NULL 
        END,
        promotion_expires = CASE 
            WHEN p_new_state = 'HOT' THEN now() + INTERVAL '24 hours'
            ELSE NULL 
        END,
        consecutive_hot = CASE 
            WHEN p_new_state = 'HOT' THEN consecutive_hot + 1
            ELSE 0
        END
    WHERE ticker = p_ticker;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_markov_state IS 'Transitions a ticker to a new Markov state and calculates next update time';


-- Function: Log a pipeline run
CREATE OR REPLACE FUNCTION start_pipeline_run(p_run_type TEXT)
RETURNS UUID AS $$
DECLARE
    run_id UUID;
BEGIN
    INSERT INTO pipeline_runs (run_type, status)
    VALUES (p_run_type, 'running')
    RETURNING id INTO run_id;
    
    RETURN run_id;
END;
$$ LANGUAGE plpgsql;


-- Function: Complete a pipeline run
CREATE OR REPLACE FUNCTION complete_pipeline_run(
    p_run_id UUID,
    p_status TEXT,
    p_markov_count INTEGER DEFAULT 0,
    p_collected INTEGER DEFAULT 0,
    p_scored INTEGER DEFAULT 0,
    p_promoted INTEGER DEFAULT 0,
    p_demoted INTEGER DEFAULT 0,
    p_api_calls INTEGER DEFAULT 0,
    p_api_errors INTEGER DEFAULT 0,
    p_error_message TEXT DEFAULT NULL,
    p_error_step TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE pipeline_runs SET
        finished_at = now(),
        duration_seconds = EXTRACT(EPOCH FROM (now() - started_at)),
        status = p_status,
        markov_tickers_due = p_markov_count,
        collected_count = p_collected,
        scored_count = p_scored,
        states_promoted = p_promoted,
        states_demoted = p_demoted,
        api_calls_made = p_api_calls,
        api_errors = p_api_errors,
        error_message = p_error_message,
        error_step = p_error_step
    WHERE id = p_run_id;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- CLEANUP — Auto-delete old data to stay within free tier
-- ============================================================

-- Delete score history older than 90 days (run weekly via cron)
CREATE OR REPLACE FUNCTION cleanup_old_data()
RETURNS VOID AS $$
BEGIN
    DELETE FROM score_history WHERE recorded_at < now() - INTERVAL '90 days';
    DELETE FROM pipeline_runs WHERE started_at < now() - INTERVAL '30 days';
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- DONE! Schema is ready.
-- ============================================================
-- Next steps:
-- 1. Run this SQL in Supabase SQL Editor
-- 2. Load tickers via init_tickers.py (Step 0 in pipeline)
-- 3. Deploy Edge Functions
-- 4. Set up n8n cron triggers
-- ============================================================
