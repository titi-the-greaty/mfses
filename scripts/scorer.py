"""
SeeSaw MFSES — Scorer (Step 3 of Pipeline)
=============================================
Reads raw data from Supabase (written by collector in Step 2).
Calculates all 6 MFSES factor scores (0-20 each).
Calculates Graham Number and upside %.
Calculates 3 time horizon composite scores.
Writes results to stock_scores table.

This is the BRAIN of MFSES — all the formulas live here.
"""

import os
import json
from datetime import datetime, timezone
from supabase import create_client, Client

# ============================================================
# CONFIG
# ============================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")


# ============================================================
# FACTOR 1: MOAT SCORE (0-20)
# ============================================================
# Market cap as proxy for competitive advantage.
# Bigger company = wider moat = harder to disrupt.

MOAT_THRESHOLDS = [
    (1_000_000_000_000, 20),   # $1T+
    (500_000_000_000,   19),   # $500B+
    (200_000_000_000,   18),   # $200B+
    (100_000_000_000,   18),   # $100B+  (same as $200B — both mega)
    (50_000_000_000,    16),   # $50B+
    (10_000_000_000,    15),   # $10B+
    (5_000_000_000,     13),   # $5B+
    (2_000_000_000,     12),   # $2B+
    (1_000_000_000,     10),   # $1B+
]
MOAT_DEFAULT = 8               # < $1B

def score_moat(market_cap: int | None) -> int:
    """Score market cap as a moat proxy. Returns 0-20."""
    if not market_cap or market_cap <= 0:
        return MOAT_DEFAULT
    
    for threshold, score in MOAT_THRESHOLDS:
        if market_cap >= threshold:
            return score
    
    return MOAT_DEFAULT


# ============================================================
# FACTOR 2: GROWTH SCORE (0-20)
# ============================================================
# Year-over-year EPS growth rate.
# High growth = strong earnings momentum.

GROWTH_THRESHOLDS = [
    (100, 20),   # 100%+ growth
    (66,  19),   # 66%+
    (50,  18),   # 50%+
    (40,  17),   # 40%+
    (30,  16),   # 30%+
    (25,  15),   # 25%+
    (20,  14),   # 20%+
    (15,  13),   # 15%+
    (10,  12),   # 10%+
    (5,   10),   # 5%+
    (0,    8),   # 0-5% (flat)
    (-5,   6),   # Slight decline
]
GROWTH_DEFAULT = 4             # Declining > 5%

def score_growth(eps_growth_rate: float | None) -> int:
    """Score EPS growth rate. Returns 0-20."""
    if eps_growth_rate is None:
        return 8  # Unknown = neutral
    
    for threshold, score in GROWTH_THRESHOLDS:
        if eps_growth_rate >= threshold:
            return score
    
    return GROWTH_DEFAULT


# ============================================================
# FACTOR 3: BALANCE SCORE (0-20)
# ============================================================
# Debt-to-equity ratio.
# Lower debt = more financial resilience.

BALANCE_THRESHOLDS = [
    (0.1, 20),   # Almost no debt
    (0.2, 19),   # Very low
    (0.3, 18),   # Low
    (0.5, 16),   # Moderate
    (0.7, 14),   # Acceptable
    (1.0, 12),   # Moderate-high
    (1.5, 10),   # High
    (2.0,  8),   # Very high
    (3.0,  6),   # Dangerous
]
BALANCE_DEFAULT = 4            # Extreme debt (D/E > 3.0)
BALANCE_NEGATIVE_EQUITY = 2    # Red flag: negative shareholder equity

def score_balance(debt_to_equity: float | None, shareholders_equity: int | None = None) -> int:
    """Score debt-to-equity ratio. Returns 0-20."""
    # Negative equity = red flag
    if shareholders_equity is not None and shareholders_equity < 0:
        return BALANCE_NEGATIVE_EQUITY
    
    if debt_to_equity is None:
        return 10  # Unknown = below-neutral
    
    if debt_to_equity < 0:
        # Negative D/E usually means negative debt (net cash) = great
        return 20
    
    for threshold, score in BALANCE_THRESHOLDS:
        if debt_to_equity <= threshold:
            return score
    
    return BALANCE_DEFAULT


# ============================================================
# FACTOR 4: VALUATION SCORE (0-20)
# ============================================================
# Graham Number: intrinsic value vs current price.
# Positive upside = undervalued = good.
#
# Graham Formula:
#   g_capped = min(eps_growth_rate, 25)     ← cap growth at 25% for conservatism
#   graham_value = EPS × (8.5 + 2 × g_capped)
#   upside_pct = ((graham_value - price) / price) × 100

VALUATION_THRESHOLDS = [
    (100,  20),   # 100%+ undervalued (2x upside)
    (75,   19),   # 75-100%
    (50,   18),   # 50-75%
    (40,   17),   # 40-50%
    (30,   16),   # 30-40%
    (20,   15),   # 20-30%
    (10,   14),   # 10-20%
    (5,    13),   # 5-10%
    (0,    12),   # Fairly valued
    (-10,  10),   # Slightly overvalued
    (-20,   8),   # Moderately overvalued
    (-30,   6),   # Overvalued
]
VALUATION_DEFAULT = 4          # Severely overvalued (< -30%)

GRAHAM_GROWTH_CAP = 25         # Max growth rate used in Graham formula
GRAHAM_BASE_PE = 8.5           # P/E for a no-growth company

def calculate_graham(eps: float | None, eps_growth_rate: float | None) -> float | None:
    """
    Calculate Graham Number (intrinsic value per share).
    Returns None if EPS data is insufficient.
    """
    if eps is None or eps <= 0:
        return None
    
    growth = eps_growth_rate if eps_growth_rate is not None else 0
    g_capped = min(max(growth, 0), GRAHAM_GROWTH_CAP)  # Clamp: 0 to 25
    
    graham_value = eps * (GRAHAM_BASE_PE + 2 * g_capped)
    return round(graham_value, 4)


def calculate_upside(graham_value: float | None, price: float | None) -> float | None:
    """Calculate upside % of Graham value vs current price."""
    if graham_value is None or price is None or price <= 0:
        return None
    return round(((graham_value - price) / price) * 100, 2)


def score_valuation(upside_pct: float | None) -> int:
    """Score Graham upside percentage. Returns 0-20."""
    if upside_pct is None:
        return 10  # Unknown = slightly below neutral
    
    for threshold, score in VALUATION_THRESHOLDS:
        if upside_pct >= threshold:
            return score
    
    return VALUATION_DEFAULT


# ============================================================
# FACTOR 5: SENTIMENT SCORE (0-20)
# ============================================================
# Placeholder for now. Future: Claude API news analysis.
# All stocks get neutral 12 until NewsIQ is integrated.

SENTIMENT_DEFAULT = 12

def score_sentiment(news_count_1h: int | None = None, news_count_24h: int | None = None) -> int:
    """
    Score market sentiment. Currently returns neutral placeholder.
    
    Future implementation will analyze:
    - News article sentiment via Claude API
    - Reddit/social media sentiment
    - Analyst rating changes
    - Insider buying/selling
    """
    # TODO: Integrate NewsIQ (Claude API sentiment analysis)
    # For now, return neutral
    return SENTIMENT_DEFAULT


# ============================================================
# FACTOR 6: DIVIDENDS SCORE (0-20)
# ============================================================
# Dividend yield + payout ratio sustainability.
# High yield with sustainable payout = good.
# Unsustainable payout (>100%) = penalty.

DIVIDEND_YIELD_THRESHOLDS = [
    (6.0, 18),   # 6%+ yield
    (5.0, 17),   # 5%+
    (4.0, 16),   # 4%+
    (3.5, 15),   # 3.5%+
    (3.0, 14),   # 3%+
    (2.5, 13),   # 2.5%+
    (2.0, 12),   # 2%+
    (1.5, 11),   # 1.5%+
    (1.0, 10),   # 1%+
    (0.5,  8),   # 0.5%+
]
DIVIDEND_NO_YIELD = 5          # No dividend at all

# Payout ratio adjustments
PAYOUT_UNSUSTAINABLE = -5      # > 100% (paying more than earning)
PAYOUT_RISKY = -2              # > 80%
PAYOUT_ACCEPTABLE = 0          # 40-80%
PAYOUT_ROOM_TO_GROW = 2        # < 40% (can increase dividend)

def score_dividends(dividend_yield: float | None, payout_ratio: float | None) -> int:
    """
    Score dividend yield with payout ratio adjustment. Returns 0-20.
    
    Base score from yield, then adjust for payout sustainability.
    Final score clamped to [0, 20].
    """
    # Base score from yield
    if dividend_yield is None or dividend_yield <= 0:
        base = DIVIDEND_NO_YIELD
    else:
        base = DIVIDEND_NO_YIELD  # Default if below all thresholds
        for threshold, score in DIVIDEND_YIELD_THRESHOLDS:
            if dividend_yield >= threshold:
                base = score
                break
    
    # Payout ratio adjustment
    adjustment = 0
    if payout_ratio is not None and dividend_yield and dividend_yield > 0:
        if payout_ratio > 100:
            adjustment = PAYOUT_UNSUSTAINABLE     # -5
        elif payout_ratio > 80:
            adjustment = PAYOUT_RISKY             # -2
        elif payout_ratio < 40:
            adjustment = PAYOUT_ROOM_TO_GROW      # +2
        # else: 40-80% = acceptable, no adjustment
    
    # Clamp to [0, 20]
    return max(0, min(20, base + adjustment))


# ============================================================
# TIME HORIZON COMPOSITES (0.0 - 20.0)
# ============================================================
# Same 6 factors, different weights per investment timeframe.
# All weights sum to 1.0 for each horizon.

def composite_short(moat, growth, balance, valuation, sentiment, dividends) -> float:
    """
    SHORT-TERM (0-6 months): Momentum and sentiment drive quick trades.
    
    growth×0.35 + valuation×0.20 + sentiment×0.15 + moat×0.15 + balance×0.10 + dividends×0.05
    """
    return round(
        growth     * 0.35 +
        valuation  * 0.20 +
        sentiment  * 0.15 +
        moat       * 0.15 +
        balance    * 0.10 +
        dividends  * 0.05,
        2
    )


def composite_mid(moat, growth, balance, valuation, sentiment, dividends) -> float:
    """
    MID-TERM (2-3 years): Balanced approach — quality at fair prices.
    
    moat×0.30 + valuation×0.20 + growth×0.20 + balance×0.15 + dividends×0.10 + sentiment×0.05
    """
    return round(
        moat       * 0.30 +
        valuation  * 0.20 +
        growth     * 0.20 +
        balance    * 0.15 +
        dividends  * 0.10 +
        sentiment  * 0.05,
        2
    )


def composite_long(moat, growth, balance, valuation, sentiment, dividends) -> float:
    """
    LONG-TERM (5+ years): Moat and balance dominate — Buffett style.
    
    moat×0.30 + balance×0.25 + dividends×0.15 + valuation×0.15 + growth×0.10 + sentiment×0.05
    """
    return round(
        moat       * 0.30 +
        balance    * 0.25 +
        dividends  * 0.15 +
        valuation  * 0.15 +
        growth     * 0.10 +
        sentiment  * 0.05,
        2
    )


# ============================================================
# SCORE ONE STOCK
# ============================================================

def score_stock(raw: dict) -> dict:
    """
    Calculate all MFSES scores for a single stock.
    
    Input: raw data dict from stock_raw_data table.
    Output: scores dict ready for stock_scores table.
    """
    ticker = raw["ticker"]
    
    # --- Extract raw values ---
    market_cap = raw.get("market_cap")
    eps_current = raw.get("eps_current")
    eps_growth_rate = raw.get("eps_growth_rate")
    debt_to_equity = raw.get("debt_to_equity")
    shareholders_equity = raw.get("shareholders_equity")
    price = raw.get("price")
    dividend_yield = raw.get("dividend_yield")
    payout_ratio = raw.get("payout_ratio")
    news_1h = raw.get("news_count_1h")
    news_24h = raw.get("news_count_24h")
    
    # --- Calculate 6 Factor Scores ---
    moat       = score_moat(market_cap)
    growth     = score_growth(eps_growth_rate)
    balance    = score_balance(debt_to_equity, shareholders_equity)
    
    # Graham valuation
    graham_value = calculate_graham(eps_current, eps_growth_rate)
    upside_pct = calculate_upside(graham_value, price)
    valuation  = score_valuation(upside_pct)
    
    sentiment  = score_sentiment(news_1h, news_24h)
    dividends  = score_dividends(dividend_yield, payout_ratio)
    
    # --- Calculate Composites ---
    mfses_short = composite_short(moat, growth, balance, valuation, sentiment, dividends)
    mfses_mid   = composite_mid(moat, growth, balance, valuation, sentiment, dividends)
    mfses_long  = composite_long(moat, growth, balance, valuation, sentiment, dividends)
    
    return {
        "ticker":            ticker,
        "moat_score":        moat,
        "growth_score":      growth,
        "balance_score":     balance,
        "valuation_score":   valuation,
        "sentiment_score":   sentiment,
        "dividend_score":    dividends,
        "mfses_short":       mfses_short,
        "mfses_mid":         mfses_mid,
        "mfses_long":        mfses_long,
        "graham_value":      graham_value,
        "graham_upside_pct": upside_pct,
        "scored_at":         datetime.now(timezone.utc).isoformat(),
    }


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def init_supabase() -> Client:
    """Initialize Supabase client."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def run_scorer(tickers: list[str]) -> dict:
    """
    Main entry point. Called by n8n after collector.py.
    
    Reads raw data for given tickers from Supabase.
    Scores each stock using MFSES formulas.
    Writes scores to stock_scores table.
    Optionally snapshots to score_history (once per day).
    
    Args:
        tickers: List of ticker symbols to score.
    
    Returns:
        {
            "scored": 47,
            "failed": 0,
            "avg_short": 13.2,
            "avg_mid": 12.8,
            "avg_long": 13.5,
            "triple_crowns": 3,
            "errors": []
        }
    """
    if not tickers:
        return {"scored": 0, "failed": 0, "errors": []}
    
    supabase = init_supabase()
    
    # Fetch raw data for all tickers
    # Supabase .in_() has a limit, so batch if needed
    all_raw = []
    batch_size = 200
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        result = supabase.table("stock_raw_data") \
            .select("*") \
            .in_("ticker", batch) \
            .execute()
        all_raw.extend(result.data or [])
    
    print(f"🧮 Scoring {len(all_raw)} stocks...")
    
    scored = 0
    failed = 0
    errors = []
    all_scores = []
    
    for raw in all_raw:
        try:
            scores = score_stock(raw)
            all_scores.append(scores)
            scored += 1
        except Exception as e:
            failed += 1
            errors.append(f"{raw.get('ticker', '?')}: {str(e)[:100]}")
            print(f"  ❌ Scoring failed for {raw.get('ticker', '?')}: {e}")
    
    # Batch upsert scores to Supabase
    if all_scores:
        # Batch in groups of 100 for Supabase
        for i in range(0, len(all_scores), 100):
            batch = all_scores[i:i + 100]
            try:
                supabase.table("stock_scores") \
                    .upsert(batch, on_conflict="ticker") \
                    .execute()
            except Exception as e:
                print(f"  ❌ Batch upsert failed: {e}")
                # Fallback: try one at a time
                for s in batch:
                    try:
                        supabase.table("stock_scores") \
                            .upsert(s, on_conflict="ticker") \
                            .execute()
                    except Exception as e2:
                        failed += 1
                        scored -= 1
                        errors.append(f"{s['ticker']}: DB write failed - {str(e2)[:50]}")
    
    # Calculate summary stats
    shorts = [s["mfses_short"] for s in all_scores if s.get("mfses_short")]
    mids = [s["mfses_mid"] for s in all_scores if s.get("mfses_mid")]
    longs = [s["mfses_long"] for s in all_scores if s.get("mfses_long")]
    
    triple_crowns = sum(
        1 for s in all_scores
        if s.get("mfses_short", 0) >= 14
        and s.get("mfses_mid", 0) >= 14
        and s.get("mfses_long", 0) >= 14
    )
    
    result = {
        "scored": scored,
        "failed": failed,
        "avg_short": round(sum(shorts) / len(shorts), 2) if shorts else 0,
        "avg_mid": round(sum(mids) / len(mids), 2) if mids else 0,
        "avg_long": round(sum(longs) / len(longs), 2) if longs else 0,
        "triple_crowns": triple_crowns,
        "errors": errors[:20],
    }
    
    print(f"\n{'='*60}")
    print(f"Scoring complete:")
    print(f"  ✅ Scored: {scored}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📊 Avg Short: {result['avg_short']}")
    print(f"  📊 Avg Mid:   {result['avg_mid']}")
    print(f"  📊 Avg Long:  {result['avg_long']}")
    print(f"  👑 Triple Crowns: {triple_crowns}")
    print(f"{'='*60}")
    
    return result


def snapshot_daily_scores(tickers: list[str] = None):
    """
    Save a daily snapshot of scores to score_history table.
    Call this once per day (e.g., at market close 4PM ET).
    Used for trend analysis ("AAPL was 14.2 last week, now 16.1").
    """
    supabase = init_supabase()
    
    query = supabase.table("stock_scores") \
        .select("ticker, moat_score, growth_score, balance_score, valuation_score, "
                "sentiment_score, dividend_score, total_score, mfses_short, mfses_mid, "
                "mfses_long, graham_upside_pct")
    
    if tickers:
        # Only snapshot specific tickers
        for i in range(0, len(tickers), 200):
            batch = tickers[i:i + 200]
            result = query.in_("ticker", batch).execute()
            _write_history(supabase, result.data)
    else:
        # Snapshot all
        result = query.execute()
        _write_history(supabase, result.data)


def _write_history(supabase: Client, scores: list[dict]):
    """Write score snapshots to score_history table."""
    if not scores:
        return
    
    # Get current prices
    tickers = [s["ticker"] for s in scores]
    prices = {}
    for i in range(0, len(tickers), 200):
        batch = tickers[i:i + 200]
        result = supabase.table("stock_raw_data") \
            .select("ticker, price") \
            .in_("ticker", batch) \
            .execute()
        for r in (result.data or []):
            prices[r["ticker"]] = r.get("price")
    
    now = datetime.now(timezone.utc).isoformat()
    history_records = []
    
    for s in scores:
        record = {
            "ticker": s["ticker"],
            "recorded_at": now,
            "moat_score": s.get("moat_score"),
            "growth_score": s.get("growth_score"),
            "balance_score": s.get("balance_score"),
            "valuation_score": s.get("valuation_score"),
            "sentiment_score": s.get("sentiment_score"),
            "dividend_score": s.get("dividend_score"),
            "total_score": s.get("total_score"),
            "mfses_short": s.get("mfses_short"),
            "mfses_mid": s.get("mfses_mid"),
            "mfses_long": s.get("mfses_long"),
            "graham_upside_pct": s.get("graham_upside_pct"),
            "price": prices.get(s["ticker"]),
        }
        history_records.append(record)
    
    # Batch insert
    for i in range(0, len(history_records), 100):
        batch = history_records[i:i + 100]
        try:
            supabase.table("score_history").insert(batch).execute()
        except Exception as e:
            print(f"  ⚠️  History snapshot batch failed: {e}")


# ============================================================
# STANDALONE EXECUTION (for testing)
# ============================================================

if __name__ == "__main__":
    import sys
    
    # Test with sample data (no DB needed)
    if "--test" in sys.argv:
        print("Running formula tests...\n")
        
        # AAPL example from our docs
        test_raw = {
            "ticker": "AAPL",
            "market_cap": 3_800_000_000_000,
            "eps_current": 6.57,
            "eps_growth_rate": 10.0,
            "debt_to_equity": 1.84,
            "shareholders_equity": 62_146_000_000,
            "price": 248.35,
            "dividend_yield": 0.44,
            "payout_ratio": 15.2,
            "news_count_1h": 2,
            "news_count_24h": 15,
        }
        
        scores = score_stock(test_raw)
        
        print(f"{'='*50}")
        print(f"AAPL Score Breakdown:")
        print(f"{'='*50}")
        print(f"  🏰 Moat:       {scores['moat_score']}/20  (market cap: $3.8T)")
        print(f"  📈 Growth:     {scores['growth_score']}/20  (EPS growth: 10%)")
        print(f"  ⚖️  Balance:    {scores['balance_score']}/20  (D/E: 1.84)")
        print(f"  💎 Valuation:  {scores['valuation_score']}/20  (Graham: ${scores['graham_value']}, Upside: {scores['graham_upside_pct']}%)")
        print(f"  🧠 Sentiment:  {scores['sentiment_score']}/20  (placeholder)")
        print(f"  💰 Dividends:  {scores['dividend_score']}/20  (yield: 0.44%, payout: 15.2%)")
        print(f"  {'─'*46}")
        print(f"  Total: {scores['moat_score'] + scores['growth_score'] + scores['balance_score'] + scores['valuation_score'] + scores['sentiment_score'] + scores['dividend_score']}/120")
        print(f"")
        print(f"  ⏱️  Short-term: {scores['mfses_short']}/20")
        print(f"  ⏱️  Mid-term:   {scores['mfses_mid']}/20")
        print(f"  ⏱️  Long-term:  {scores['mfses_long']}/20")
        print(f"{'='*50}")
        
        # Test a few more
        print(f"\nMore examples:")
        
        tests = [
            {"ticker": "NVDA", "market_cap": 2_900_000_000_000, "eps_current": 2.94,
             "eps_growth_rate": 66.0, "debt_to_equity": 0.41, "shareholders_equity": 42_000_000_000,
             "price": 140.0, "dividend_yield": 0.03, "payout_ratio": 1.4},
            
            {"ticker": "KO", "market_cap": 270_000_000_000, "eps_current": 2.47,
             "eps_growth_rate": 8.0, "debt_to_equity": 1.72, "shareholders_equity": 25_000_000_000,
             "price": 62.0, "dividend_yield": 3.1, "payout_ratio": 75.0},
            
            {"ticker": "SMCI", "market_cap": 15_000_000_000, "eps_current": 1.80,
             "eps_growth_rate": 120.0, "debt_to_equity": 0.35, "shareholders_equity": 3_500_000_000,
             "price": 30.0, "dividend_yield": 0.0, "payout_ratio": 0.0},
        ]
        
        for t in tests:
            s = score_stock(t)
            total = s["moat_score"] + s["growth_score"] + s["balance_score"] + s["valuation_score"] + s["sentiment_score"] + s["dividend_score"]
            print(f"  {t['ticker']:5s} | Moat:{s['moat_score']:2d} Grw:{s['growth_score']:2d} Bal:{s['balance_score']:2d} Val:{s['valuation_score']:2d} Sen:{s['sentiment_score']:2d} Div:{s['dividend_score']:2d} | Total:{total:3d}/120 | Short:{s['mfses_short']:5.2f} Mid:{s['mfses_mid']:5.2f} Long:{s['mfses_long']:5.2f}")
    
    else:
        # Run against Supabase
        test_tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
        if len(sys.argv) > 1 and sys.argv[1] != "--test":
            test_tickers = [t for t in sys.argv[1:] if t != "--test"]
        
        print(f"{'='*60}")
        print(f"SeeSaw MFSES — Scorer")
        print(f"Tickers: {test_tickers}")
        print(f"{'='*60}")
        
        result = run_scorer(test_tickers)
        print(f"\nResult: {json.dumps(result, indent=2)}")
