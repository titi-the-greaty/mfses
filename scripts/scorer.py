"""
SeeSaw MFSES â Scorer v2 (Step 3 of Pipeline)
==============================================
NEW FORMULAS:
- Moat = (Market Cap score Ã 0.5) + (Analyst Rating score Ã 0.5)
- Growth = (EPS Growth score Ã 0.66) + (OBV Trend score Ã 0.33)
- Balance = Same (D/E ratio)
- Valuation = Bond-adjusted Graham: (EPS Ã (8.5 + 2g) Ã 4.4) / Y
- Sentiment = (Analyst Rating score Ã 0.5) + (Short Interest inverse Ã 0.5)
- Dividends = Same

Reads from Supabase stock_raw_data, writes to stock_scores.
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

# Graham bond yield adjustment
GRAHAM_ORIGINAL_YIELD = 4.4   # AAA yield when Graham wrote formula (1962)
CURRENT_AAA_YIELD = 5.15      # Current AAA corporate bond yield (update quarterly)


# ============================================================
# COMPONENT SCORES (used to build factor scores)
# ============================================================

# --- Market Cap Score (0-20) ---
MARKET_CAP_THRESHOLDS = [
    (1_000_000_000_000, 20),   # $1T+
    (500_000_000_000,   19),   # $500B+
    (200_000_000_000,   18),   # $200B+
    (100_000_000_000,   17),   # $100B+
    (50_000_000_000,    15),   # $50B+
    (20_000_000_000,    13),   # $20B+
    (10_000_000_000,    12),   # $10B+
    (5_000_000_000,     10),   # $5B+
    (2_000_000_000,      8),   # $2B+
    (1_000_000_000,      6),   # $1B+
]
MARKET_CAP_DEFAULT = 4

def score_market_cap(market_cap: int | None) -> int:
    """Score market cap alone. Returns 0-20."""
    if not market_cap or market_cap <= 0:
        return MARKET_CAP_DEFAULT

    for threshold, score in MARKET_CAP_THRESHOLDS:
        if market_cap >= threshold:
            return score

    return MARKET_CAP_DEFAULT


# --- Analyst Rating Score (0-20) ---
# Analyst rating is typically 1-5 scale (1=strong sell, 5=strong buy)
def score_analyst_rating(rating: float | None) -> int:
    """Score analyst rating. Returns 0-20."""
    if rating is None:
        return 10  # Neutral if unknown

    # Scale 1-5 to 0-20
    # 1.0 â 0, 2.0 â 5, 3.0 â 10, 4.0 â 15, 5.0 â 20
    score = (rating - 1) * 5
    return max(0, min(20, int(round(score))))


# --- EPS Growth Score (0-20) ---
# Tightened thresholds
EPS_GROWTH_THRESHOLDS = [
    (150, 20),   # 150%+ (was 100%)
    (100, 19),   # 100%+
    (75,  18),   # 75%+
    (50,  17),   # 50%+
    (40,  16),   # 40%+
    (30,  15),   # 30%+
    (25,  14),   # 25%+
    (20,  13),   # 20%+
    (15,  12),   # 15%+
    (10,  11),   # 10%+
    (5,   10),   # 5%+
    (0,    8),   # Flat
    (-10,  6),   # Slight decline
    (-25,  4),   # Moderate decline
]
EPS_GROWTH_DEFAULT = 2

def score_eps_growth(eps_growth_rate: float | None) -> int:
    """Score EPS growth rate alone. Returns 0-20."""
    if eps_growth_rate is None:
        return 8  # Neutral if unknown

    for threshold, score in EPS_GROWTH_THRESHOLDS:
        if eps_growth_rate >= threshold:
            return score

    return EPS_GROWTH_DEFAULT


# --- OBV Trend Score (0-20) ---
# Based on OBV trend and price/OBV divergence
def score_obv_trend(obv_trend: float | None, divergence: float | None) -> int:
    """
    Score OBV trend. Returns 0-20.

    obv_trend: % change in OBV over 20 days
    divergence: OBV trend minus price trend (positive = bullish divergence)
    """
    if obv_trend is None:
        return 10  # Neutral if unknown

    score = 10  # Start neutral

    # OBV trend component
    if obv_trend > 50:
        score += 5
    elif obv_trend > 25:
        score += 4
    elif obv_trend > 10:
        score += 3
    elif obv_trend > 5:
        score += 2
    elif obv_trend > 0:
        score += 1
    elif obv_trend > -5:
        score += 0
    elif obv_trend > -10:
        score -= 1
    elif obv_trend > -25:
        score -= 3
    else:
        score -= 5

    # Divergence component (OBV rising while price falling = bullish)
    if divergence is not None:
        if divergence > 20:
            score += 5   # Strong bullish divergence
        elif divergence > 10:
            score += 3
        elif divergence > 5:
            score += 2
        elif divergence > -5:
            score += 0   # No divergence
        elif divergence > -10:
            score -= 2
        elif divergence > -20:
            score -= 3
        else:
            score -= 5   # Strong bearish divergence

    return max(0, min(20, score))


# --- Balance Score (D/E) --- UNCHANGED
BALANCE_THRESHOLDS = [
    (0.1, 20),
    (0.2, 19),
    (0.3, 18),
    (0.5, 16),
    (0.7, 14),
    (1.0, 12),
    (1.5, 10),
    (2.0,  8),
    (3.0,  6),
]
BALANCE_DEFAULT = 4
BALANCE_NEGATIVE_EQUITY = 2

def score_balance(debt_to_equity: float | None, shareholders_equity: int | None = None) -> int:
    """Score debt-to-equity ratio. Returns 0-20."""
    if shareholders_equity is not None and shareholders_equity < 0:
        return BALANCE_NEGATIVE_EQUITY

    if debt_to_equity is None:
        return 10

    if debt_to_equity < 0:
        return 20  # Net cash position

    for threshold, score in BALANCE_THRESHOLDS:
        if debt_to_equity <= threshold:
            return score

    return BALANCE_DEFAULT


# --- Valuation Score (Graham Upside) ---
# TIGHTENED thresholds
VALUATION_THRESHOLDS = [
    (150, 20),   # 150%+ undervalued (was 100%)
    (100, 19),   # 100%+ undervalued
    (75,  18),   # 75%+
    (50,  17),   # 50%+
    (40,  16),   # 40%+
    (30,  15),   # 30%+
    (20,  14),   # 20%+
    (10,  13),   # 10%+
    (5,   12),   # 5%+
    (0,   11),   # Fairly valued
    (-10, 10),   # Slightly overvalued
    (-20,  8),   # Moderately overvalued
    (-30,  6),   # Overvalued
    (-50,  4),   # Very overvalued
]
VALUATION_DEFAULT = 2

def calculate_graham_adjusted(eps: float | None, eps_growth_rate: float | None) -> float | None:
    """
    Calculate bond-adjusted Graham Number.
    Formula: (EPS Ã (8.5 + 2g) Ã 4.4) / Y
    Where Y = current AAA bond yield
    """
    if eps is None or eps <= 0:
        return None

    growth = eps_growth_rate if eps_growth_rate is not None else 0
    g_capped = min(max(growth, 0), 25)  # Cap growth at 25%

    graham_value = (eps * (8.5 + 2 * g_capped) * GRAHAM_ORIGINAL_YIELD) / CURRENT_AAA_YIELD
    return round(graham_value, 4)


def calculate_upside(graham_value: float | None, price: float | None) -> float | None:
    """Calculate upside % of Graham value vs current price."""
    if graham_value is None or price is None or price <= 0:
        return None
    return round(((graham_value - price) / price) * 100, 2)


def score_valuation(upside_pct: float | None) -> int:
    """Score Graham upside percentage. Returns 0-20."""
    if upside_pct is None:
        return 10

    for threshold, score in VALUATION_THRESHOLDS:
        if upside_pct >= threshold:
            return score

    return VALUATION_DEFAULT


# --- Short Interest Score (0-20) ---
# High short interest = bearish = LOW score (inverse)
def score_short_interest(short_interest_pct: float | None) -> int:
    """
    Score short interest (inverse - high short = low score).
    Returns 0-20.
    """
    if short_interest_pct is None:
        return 10  # Neutral if unknown

    # Typical ranges: <2% low, 2-5% normal, 5-10% elevated, >10% high
    if short_interest_pct < 1:
        return 20
    elif short_interest_pct < 2:
        return 18
    elif short_interest_pct < 3:
        return 16
    elif short_interest_pct < 5:
        return 14
    elif short_interest_pct < 7:
        return 12
    elif short_interest_pct < 10:
        return 10
    elif short_interest_pct < 15:
        return 8
    elif short_interest_pct < 20:
        return 6
    elif short_interest_pct < 30:
        return 4
    else:
        return 2


# --- Dividends Score --- UNCHANGED
DIVIDEND_YIELD_THRESHOLDS = [
    (6.0, 18),
    (5.0, 17),
    (4.0, 16),
    (3.5, 15),
    (3.0, 14),
    (2.5, 13),
    (2.0, 12),
    (1.5, 11),
    (1.0, 10),
    (0.5,  8),
]
DIVIDEND_NO_YIELD = 5
PAYOUT_UNSUSTAINABLE = -5
PAYOUT_RISKY = -2
PAYOUT_ROOM_TO_GROW = 2

def score_dividends(dividend_yield: float | None, payout_ratio: float | None) -> int:
    """Score dividend yield with payout ratio adjustment. Returns 0-20."""
    if dividend_yield is None or dividend_yield <= 0:
        base = DIVIDEND_NO_YIELD
    else:
        base = DIVIDEND_NO_YIELD
        for threshold, score in DIVIDEND_YIELD_THRESHOLDS:
            if dividend_yield >= threshold:
                base = score
                break

    adjustment = 0
    if payout_ratio is not None and dividend_yield and dividend_yield > 0:
        if payout_ratio > 100:
            adjustment = PAYOUT_UNSUSTAINABLE
        elif payout_ratio > 80:
            adjustment = PAYOUT_RISKY
        elif payout_ratio < 40:
            adjustment = PAYOUT_ROOM_TO_GROW

    return max(0, min(20, base + adjustment))


# ============================================================
# MAIN FACTOR SCORES (combining components)
# ============================================================

def calculate_moat_score(market_cap: int | None, analyst_rating: float | None) -> int:
    """
    MOAT = (Market Cap score Ã 0.67) + (Analyst Rating score Ã 0.33)
    """
    mc_score = score_market_cap(market_cap)
    ar_score = score_analyst_rating(analyst_rating)

    combined = (mc_score * 0.67) + (ar_score * 0.33)
    return max(0, min(20, int(round(combined))))


def calculate_growth_score(eps_growth_rate: float | None, obv_trend: float | None, obv_divergence: float | None) -> int:
    """
    GROWTH = (EPS Growth score Ã 0.66) + (OBV Trend score Ã 0.33)
    """
    eps_score = score_eps_growth(eps_growth_rate)
    obv_score = score_obv_trend(obv_trend, obv_divergence)

    combined = (eps_score * 0.66) + (obv_score * 0.33)
    return max(0, min(20, int(round(combined))))


def calculate_sentiment_score(analyst_rating: float | None, short_interest_pct: float | None) -> int:
    """
    SENTIMENT = (Analyst Rating score Ã 0.5) + (Short Interest inverse score Ã 0.5)
    """
    ar_score = score_analyst_rating(analyst_rating)
    si_score = score_short_interest(short_interest_pct)

    combined = (ar_score * 0.5) + (si_score * 0.5)
    return max(0, min(20, int(round(combined))))


# ============================================================
# TIME HORIZON COMPOSITES (0.0 - 20.0)
# ============================================================

def composite_short(moat, growth, balance, valuation, sentiment, dividends) -> float:
    """
    SHORT-TERM (0-6 months): Momentum and sentiment drive quick trades.
    growthÃ0.35 + valuationÃ0.20 + sentimentÃ0.15 + moatÃ0.15 + balanceÃ0.10 + dividendsÃ0.05
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
    MID-TERM (2-3 years): Balanced approach â quality at fair prices.
    moatÃ0.30 + valuationÃ0.20 + growthÃ0.20 + balanceÃ0.15 + dividendsÃ0.10 + sentimentÃ0.05
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
    LONG-TERM (5+ years): Moat and balance dominate â Buffett style.
    moatÃ0.30 + balanceÃ0.25 + dividendsÃ0.15 + valuationÃ0.15 + growthÃ0.10 + sentimentÃ0.05
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
    """Calculate all MFSES v2 scores for a single stock."""
    ticker = raw["ticker"]

    # Extract raw values
    market_cap = raw.get("market_cap")
    analyst_rating = raw.get("analyst_rating")
    eps_current = raw.get("eps_current")
    eps_growth_rate = raw.get("eps_growth_rate")
    obv_trend = raw.get("obv_trend")
    obv_divergence = raw.get("obv_price_divergence")
    debt_to_equity = raw.get("debt_to_equity")
    shareholders_equity = raw.get("shareholders_equity")
    price = raw.get("price")
    short_interest_pct = raw.get("short_interest_pct")
    dividend_yield = raw.get("dividend_yield")
    payout_ratio = raw.get("payout_ratio")

    # Calculate 6 Factor Scores
    moat = calculate_moat_score(market_cap, analyst_rating)
    growth = calculate_growth_score(eps_growth_rate, obv_trend, obv_divergence)
    balance = score_balance(debt_to_equity, shareholders_equity)

    # Graham valuation (bond-adjusted)
    graham_value = calculate_graham_adjusted(eps_current, eps_growth_rate)
    upside_pct = calculate_upside(graham_value, price)
    valuation = score_valuation(upside_pct)

    sentiment = calculate_sentiment_score(analyst_rating, short_interest_pct)
    dividends = score_dividends(dividend_yield, payout_ratio)

    # Calculate Composites
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


def run_scorer(tickers: list[str] = None) -> dict:
    """
    Main entry point. Scores stocks from Supabase.
    If tickers is None, scores ALL stocks with data.
    """
    supabase = init_supabase()

    # Fetch raw data
    if tickers:
        all_raw = []
        batch_size = 200
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            result = supabase.table("stock_raw_data") \
                .select("*") \
                .in_("ticker", batch) \
                .execute()
            all_raw.extend(result.data or [])
    else:
        # Get all stocks with price data
        result = supabase.table("stock_raw_data") \
            .select("*") \
            .not_.is_("price", "null") \
            .execute()
        all_raw = result.data or []

    print(f"ð§® Scoring {len(all_raw)} stocks with MFSES v2...")

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
            print(f"  â Scoring failed for {raw.get('ticker', '?')}: {e}")

    # Batch upsert
    if all_scores:
        for i in range(0, len(all_scores), 100):
            batch = all_scores[i:i + 100]
            try:
                supabase.table("stock_scores") \
                    .upsert(batch, on_conflict="ticker") \
                    .execute()
            except Exception as e:
                print(f"  â Batch upsert failed: {e}")
                for s in batch:
                    try:
                        supabase.table("stock_scores") \
                            .upsert(s, on_conflict="ticker") \
                            .execute()
                    except Exception as e2:
                        failed += 1
                        scored -= 1
                        errors.append(f"{s['ticker']}: DB write failed")

    # Summary stats
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
    print(f"Scoring complete (MFSES v2):")
    print(f"  â Scored: {scored}")
    print(f"  â Failed: {failed}")
    print(f"  ð Avg Short: {result['avg_short']}")
    print(f"  ð Avg Mid:   {result['avg_mid']}")
    print(f"  ð Avg Long:  {result['avg_long']}")
    print(f"  ð Triple Crowns: {triple_crowns}")
    print(f"{'='*60}")

    return result


# ============================================================
# STANDALONE TEST
# ============================================================

if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        print("Running MFSES v2 formula tests...\n")

        # Test with various scenarios
        test_cases = [
            {
                "ticker": "MEGA_GROWTH",
                "market_cap": 500_000_000_000,
                "analyst_rating": 4.5,
                "eps_current": 5.0,
                "eps_growth_rate": 80,
                "obv_trend": 30,
                "obv_price_divergence": 10,
                "debt_to_equity": 0.3,
                "shareholders_equity": 50_000_000_000,
                "price": 100,
                "short_interest_pct": 2,
                "dividend_yield": 1.0,
                "payout_ratio": 20,
            },
            {
                "ticker": "VALUE_PLAY",
                "market_cap": 10_000_000_000,
                "analyst_rating": 3.5,
                "eps_current": 8.0,
                "eps_growth_rate": 10,
                "obv_trend": 5,
                "obv_price_divergence": 0,
                "debt_to_equity": 0.5,
                "shareholders_equity": 5_000_000_000,
                "price": 50,
                "short_interest_pct": 5,
                "dividend_yield": 3.5,
                "payout_ratio": 45,
            },
            {
                "ticker": "STRUGGLING",
                "market_cap": 2_000_000_000,
                "analyst_rating": 2.0,
                "eps_current": 1.0,
                "eps_growth_rate": -20,
                "obv_trend": -30,
                "obv_price_divergence": -15,
                "debt_to_equity": 2.5,
                "shareholders_equity": 500_000_000,
                "price": 25,
                "short_interest_pct": 15,
                "dividend_yield": 0,
                "payout_ratio": 0,
            },
        ]

        print(f"{'Ticker':<15} {'Moat':>5} {'Grw':>5} {'Bal':>5} {'Val':>5} {'Sen':>5} {'Div':>5} â {'Short':>6} {'Mid':>6} {'Long':>6}")
        print("â" * 85)

        for tc in test_cases:
            s = score_stock(tc)
            total = s["moat_score"] + s["growth_score"] + s["balance_score"] + s["valuation_score"] + s["sentiment_score"] + s["dividend_score"]
            print(f"{tc['ticker']:<15} {s['moat_score']:>5} {s['growth_score']:>5} {s['balance_score']:>5} {s['valuation_score']:>5} {s['sentiment_score']:>5} {s['dividend_score']:>5} â {s['mfses_short']:>6.1f} {s['mfses_mid']:>6.1f} {s['mfses_long']:>6.1f}")

        print("\nâ Test complete")

    else:
        print(f"{'='*60}")
        print(f"SeeSaw MFSES â Scorer v2")
        print(f"{'='*60}")

        result = run_scorer()
        print(f"\nResult: {json.dumps(result, indent=2)}")
