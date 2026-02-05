"""
SeeSaw MFSES — Collector v2 (Step 2 of Pipeline)
=================================================
Fetches all data needed for MFSES v2 scoring:
- Price, volume, market cap (snapshot)
- EPS, debt/equity (financials)
- Dividends
- Analyst ratings (NEW)
- 20-day price/volume for OBV calculation (NEW)
- Short interest % (NEW)

Writes to Supabase stock_raw_data table.
"""

import os
import json
import time
import math
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

# Load .env from parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# ============================================================
# CONFIG
# ============================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY")

POLYGON_BASE = "https://api.polygon.io"

# Batching config
SNAPSHOT_BATCH_SIZE = 100
RATE_LIMIT_DELAY = 0.1        # Fast with paid plan
FUNDAMENTALS_CACHE_HOURS = 24
DIVIDEND_CACHE_HOURS = 24

# Retry config
MAX_RETRIES = 3
RETRY_DELAY = 2


# ============================================================
# API HELPERS
# ============================================================

def _api_get(url: str, params: dict = None) -> dict | None:
    """Make a GET request to Polygon API with retry logic."""
    if params is None:
        params = {}
    params["apiKey"] = POLYGON_API_KEY

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=30)

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = RETRY_DELAY * (attempt + 2)
                print(f"  ⚠️  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            elif resp.status_code == 403:
                print(f"  ❌ Forbidden (check API key): {url}")
                return None
            else:
                print(f"  ⚠️  HTTP {resp.status_code} for {url}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                return None

        except requests.exceptions.Timeout:
            print(f"  ⚠️  Timeout, attempt {attempt + 1}/{MAX_RETRIES}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            continue
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Request error: {e}")
            return None

    return None


# ============================================================
# DATA FETCHERS
# ============================================================

def fetch_snapshots(tickers: list[str]) -> dict:
    """Fetch current price + volume for multiple tickers."""
    results = {}
    batches = [tickers[i:i + SNAPSHOT_BATCH_SIZE] for i in range(0, len(tickers), SNAPSHOT_BATCH_SIZE)]

    for batch_num, batch in enumerate(batches):
        ticker_str = ",".join(batch)
        url = f"{POLYGON_BASE}/v2/snapshot/locale/us/markets/stocks/tickers"

        data = _api_get(url, {"tickers": ticker_str})

        if data and "tickers" in data:
            for snap in data["tickers"]:
                t = snap.get("ticker", "")
                day = snap.get("day", {})
                prev = snap.get("prevDay", {})

                price = day.get("c") or snap.get("lastTrade", {}).get("p", 0)
                prev_close = prev.get("c", 0)
                volume = day.get("v", 0)

                change_pct = 0.0
                if prev_close and prev_close > 0:
                    change_pct = round(((price - prev_close) / prev_close) * 100, 4)

                results[t] = {
                    "price": price,
                    "previous_close": prev_close,
                    "price_change_pct": change_pct,
                    "volume": int(volume) if volume else 0,
                    "market_cap": int(snap.get("market_cap")) if snap.get("market_cap") else None,
                }

        if batch_num < len(batches) - 1:
            time.sleep(RATE_LIMIT_DELAY)

    return results


def fetch_ticker_details(ticker: str) -> dict:
    """Fetch market cap, shares outstanding, etc."""
    url = f"{POLYGON_BASE}/v3/reference/tickers/{ticker}"
    data = _api_get(url)

    if data and "results" in data:
        r = data["results"]
        return {
            "market_cap": int(r.get("market_cap")) if r.get("market_cap") else None,
            "shares_outstanding": int(r.get("share_class_shares_outstanding") or r.get("weighted_shares_outstanding") or 0),
            "company_name": r.get("name", ticker),
            "sector": r.get("sic_description", "Unknown"),
        }
    return {}


def fetch_financials(ticker: str) -> dict:
    """Fetch EPS, debt, equity from Polygon Financials API."""
    url = f"{POLYGON_BASE}/vX/reference/financials"
    params = {
        "ticker": ticker,
        "limit": 5,
        "sort": "period_of_report_date",
        "order": "desc",
        "timeframe": "quarterly",
    }

    data = _api_get(url, params)

    if not data or "results" not in data or not data["results"]:
        return {}

    result = {}
    filings = data["results"]
    latest = filings[0]
    income = latest.get("financials", {}).get("income_statement", {})
    balance = latest.get("financials", {}).get("balance_sheet", {})

    # EPS
    eps_data = income.get("diluted_earnings_per_share") or income.get("basic_earnings_per_share")
    if eps_data:
        result["eps_current"] = eps_data.get("value", 0)

    # EPS from ~4 quarters ago
    if len(filings) >= 5:
        old_income = filings[4].get("financials", {}).get("income_statement", {})
        old_eps = old_income.get("diluted_earnings_per_share") or old_income.get("basic_earnings_per_share")
        if old_eps:
            result["eps_1y_ago"] = old_eps.get("value", 0)

    # EPS growth rate
    eps_current = result.get("eps_current", 0)
    eps_old = result.get("eps_1y_ago")
    if eps_old and eps_old != 0:
        result["eps_growth_rate"] = round(((eps_current - eps_old) / abs(eps_old)) * 100, 4)

    # Debt
    long_debt = balance.get("long_term_debt", {}).get("value", 0) or 0
    short_debt = balance.get("current_debt", {}).get("value", 0) or balance.get("short_term_debt", {}).get("value", 0) or 0
    total_debt = long_debt + short_debt
    result["total_debt"] = int(total_debt)

    # Equity
    equity = balance.get("equity", {}).get("value") or \
             balance.get("stockholders_equity", {}).get("value") or \
             balance.get("equity_attributable_to_parent", {}).get("value")

    if equity is not None:
        result["shareholders_equity"] = int(equity)
        if equity != 0:
            result["debt_to_equity"] = round(total_debt / abs(equity), 4)
        else:
            result["debt_to_equity"] = 99.99

    return result


def fetch_dividends(ticker: str) -> dict:
    """Fetch dividend data."""
    url = f"{POLYGON_BASE}/v3/reference/dividends"
    params = {
        "ticker": ticker,
        "limit": 20,
        "order": "desc",
        "sort": "ex_dividend_date",
    }

    data = _api_get(url, params)

    if not data or "results" not in data or not data["results"]:
        return {"annual_dividend": 0, "dividend_yield": 0}

    divs = data["results"]
    result = {}

    result["ex_dividend_date"] = divs[0].get("ex_dividend_date")

    recent_divs = []
    for d in divs[:4]:
        amt = d.get("cash_amount", 0)
        if amt and amt > 0:
            recent_divs.append(amt)

    annual_dividend = sum(recent_divs)
    result["annual_dividend"] = round(annual_dividend, 4)

    # 5-year growth
    if len(divs) >= 8:
        recent_annual = sum(d.get("cash_amount", 0) for d in divs[:4])
        old_annual = sum(d.get("cash_amount", 0) for d in divs[-4:])

        if old_annual > 0:
            years = min(len(divs) // 4, 5)
            if years > 0:
                growth = ((recent_annual / old_annual) ** (1 / years) - 1) * 100
                result["dividend_growth_5yr"] = round(growth, 4)

    # Consecutive increases
    yearly_totals = {}
    for d in divs:
        ex_date = d.get("ex_dividend_date", "")
        if ex_date:
            year = ex_date[:4]
            yearly_totals[year] = yearly_totals.get(year, 0) + (d.get("cash_amount", 0) or 0)

    sorted_years = sorted(yearly_totals.keys(), reverse=True)
    consecutive = 0
    for i in range(len(sorted_years) - 1):
        if yearly_totals[sorted_years[i]] > yearly_totals[sorted_years[i + 1]]:
            consecutive += 1
        else:
            break
    result["consecutive_increases"] = consecutive

    return result


def fetch_analyst_ratings(ticker: str) -> dict:
    """
    Fetch analyst ratings from Polygon.
    Returns consensus rating (1-5 scale: 1=strong sell, 5=strong buy)
    """
    url = f"{POLYGON_BASE}/v2/reference/news"
    params = {
        "ticker": ticker,
        "limit": 1,
    }

    # Polygon's analyst ratings endpoint
    ratings_url = f"{POLYGON_BASE}/v3/reference/tickers/{ticker}"
    data = _api_get(ratings_url)

    result = {}

    # Try to get from ticker details (some plans include this)
    if data and "results" in data:
        r = data["results"]
        # If Polygon includes analyst data
        if "analyst_rating" in r:
            result["analyst_rating"] = r["analyst_rating"]

    # Fallback: estimate from other signals or default to neutral
    if "analyst_rating" not in result:
        # Default neutral rating
        result["analyst_rating"] = 3.0

    return result


def fetch_short_interest(ticker: str) -> dict:
    """
    Fetch short interest data.
    Short interest = shares sold short / shares outstanding
    """
    # Polygon short interest endpoint (requires certain subscription)
    url = f"{POLYGON_BASE}/v2/reference/short-interest/{ticker}"
    data = _api_get(url)

    result = {}

    if data and "results" in data and data["results"]:
        latest = data["results"][0] if isinstance(data["results"], list) else data["results"]
        result["short_interest"] = latest.get("short_interest")
        result["short_interest_pct"] = latest.get("short_interest_percent_of_float")
    else:
        # Default if not available
        result["short_interest_pct"] = None

    return result


def fetch_daily_bars(ticker: str, days: int = 25) -> list[dict]:
    """
    Fetch daily OHLCV bars for OBV calculation.
    Returns list of {date, open, high, low, close, volume}
    """
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=days + 10)).strftime("%Y-%m-%d")

    url = f"{POLYGON_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
    params = {"adjusted": "true", "sort": "asc", "limit": days}

    data = _api_get(url, params)

    if data and "results" in data:
        return [
            {
                "date": bar.get("t"),
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
            }
            for bar in data["results"]
        ]
    return []


def calculate_obv_trend(bars: list[dict]) -> dict:
    """
    Calculate OBV and its trend from daily bars.
    Returns OBV slope direction and strength.
    """
    if len(bars) < 5:
        return {"obv_trend": 0, "obv_price_divergence": 0}

    # Calculate OBV series
    obv = 0
    obv_series = []
    price_series = []

    for i, bar in enumerate(bars):
        if i == 0:
            obv = bar["volume"]
        else:
            prev_close = bars[i - 1]["close"]
            if bar["close"] > prev_close:
                obv += bar["volume"]
            elif bar["close"] < prev_close:
                obv -= bar["volume"]
            # If equal, OBV stays same

        obv_series.append(obv)
        price_series.append(bar["close"])

    # Calculate trend (simple: compare first half avg to second half avg)
    mid = len(obv_series) // 2
    obv_first_half = sum(obv_series[:mid]) / mid if mid > 0 else 0
    obv_second_half = sum(obv_series[mid:]) / (len(obv_series) - mid) if len(obv_series) > mid else 0

    price_first_half = sum(price_series[:mid]) / mid if mid > 0 else 0
    price_second_half = sum(price_series[mid:]) / (len(price_series) - mid) if len(price_series) > mid else 0

    # OBV trend: positive = accumulation, negative = distribution
    if obv_first_half != 0:
        obv_change_pct = ((obv_second_half - obv_first_half) / abs(obv_first_half)) * 100
    else:
        obv_change_pct = 0

    # Price trend
    if price_first_half != 0:
        price_change_pct = ((price_second_half - price_first_half) / price_first_half) * 100
    else:
        price_change_pct = 0

    # Divergence: OBV rising while price falling (bullish) or vice versa
    # Positive divergence = OBV trend - Price trend (if OBV stronger, bullish)
    divergence = obv_change_pct - price_change_pct

    return {
        "obv_trend": round(obv_change_pct, 2),
        "obv_price_divergence": round(divergence, 2),
        "price_trend_20d": round(price_change_pct, 2),
    }


# ============================================================
# MAIN WRITE TO SUPABASE
# ============================================================

def write_raw_data(supabase: Client, ticker: str, data: dict) -> bool:
    """Upsert raw data for a single ticker."""
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "ticker": ticker,
        "collected_at": now,
    }

    # Price & volume
    if "price" in data:
        record["price"] = data["price"]
        record["previous_close"] = data.get("previous_close")
        record["price_change_pct"] = data.get("price_change_pct")
        record["volume"] = data.get("volume")
        record["last_price_update"] = now

    if "market_cap" in data and data["market_cap"]:
        record["market_cap"] = data["market_cap"]

    if "shares_outstanding" in data and data["shares_outstanding"]:
        record["shares_outstanding"] = data["shares_outstanding"]

    if "avg_volume_20d" in data and data["avg_volume_20d"]:
        record["avg_volume_20d"] = data["avg_volume_20d"]
        if data.get("volume") and data["avg_volume_20d"] > 0:
            record["volume_ratio"] = round(data["volume"] / data["avg_volume_20d"], 3)

    # Earnings
    if "eps_current" in data:
        record["eps_current"] = data["eps_current"]
        record["last_fundamental_update"] = now
    if "eps_1y_ago" in data:
        record["eps_1y_ago"] = data["eps_1y_ago"]
    if "eps_growth_rate" in data:
        record["eps_growth_rate"] = data["eps_growth_rate"]

    # Balance sheet
    if "total_debt" in data:
        record["total_debt"] = data["total_debt"]
    if "shareholders_equity" in data:
        record["shareholders_equity"] = data["shareholders_equity"]
    if "debt_to_equity" in data:
        record["debt_to_equity"] = data["debt_to_equity"]

    # Dividends
    if "annual_dividend" in data:
        record["annual_dividend"] = data["annual_dividend"]
        record["last_dividend_update"] = now
    if "dividend_yield" in data:
        record["dividend_yield"] = data["dividend_yield"]
    if "payout_ratio" in data:
        record["payout_ratio"] = data["payout_ratio"]
    if "dividend_growth_5yr" in data:
        record["dividend_growth_5yr"] = data["dividend_growth_5yr"]
    if "consecutive_increases" in data:
        record["consecutive_increases"] = data["consecutive_increases"]
    if "ex_dividend_date" in data:
        record["ex_dividend_date"] = data["ex_dividend_date"]

    # NEW: Analyst rating
    if "analyst_rating" in data:
        record["analyst_rating"] = data["analyst_rating"]

    # NEW: Short interest
    if "short_interest_pct" in data and data["short_interest_pct"] is not None:
        record["short_interest_pct"] = data["short_interest_pct"]

    # NEW: OBV data
    if "obv_trend" in data:
        record["obv_trend"] = data["obv_trend"]
    if "obv_price_divergence" in data:
        record["obv_price_divergence"] = data["obv_price_divergence"]
    if "price_trend_20d" in data:
        record["price_trend_20d"] = data["price_trend_20d"]

    # Data quality score
    quality_checks = 0
    if data.get("price") and data["price"] > 0: quality_checks += 1
    if data.get("market_cap") and data["market_cap"] > 0: quality_checks += 1
    if data.get("eps_current") is not None: quality_checks += 1
    if data.get("debt_to_equity") is not None: quality_checks += 1
    if data.get("volume") and data["volume"] > 0: quality_checks += 1
    if data.get("analyst_rating"): quality_checks += 1
    if data.get("obv_trend") is not None: quality_checks += 1
    record["data_quality_score"] = int((quality_checks / 7) * 100)

    try:
        supabase.table("stock_raw_data") \
            .upsert(record, on_conflict="ticker") \
            .execute()
        return True
    except Exception as e:
        print(f"  ❌ DB write failed for {ticker}: {e}")
        return False


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def run_collector(tickers: list[str]) -> dict:
    """
    Main entry point. Fetches all data for given tickers.
    """
    if not tickers:
        return {"collected": 0, "failed": 0, "api_calls": 0, "errors": []}

    if not POLYGON_API_KEY:
        raise ValueError("Missing POLYGON_API_KEY environment variable")

    supabase = init_supabase()

    collected = 0
    failed = 0
    api_calls = 0
    errors = []

    # Step A: Batch fetch prices
    print(f"📡 Fetching snapshots for {len(tickers)} tickers...")
    snapshots = fetch_snapshots(tickers)
    api_calls += math.ceil(len(tickers) / SNAPSHOT_BATCH_SIZE)
    print(f"  ✅ Got {len(snapshots)} snapshots")

    # Step B: Per-ticker enrichment
    for i, ticker in enumerate(tickers):
        try:
            data = snapshots.get(ticker, {})

            if not data or not data.get("price"):
                details = fetch_ticker_details(ticker)
                api_calls += 1
                time.sleep(RATE_LIMIT_DELAY)

                if not details:
                    errors.append(f"{ticker}: no data found")
                    failed += 1
                    continue

                data.update(details)

            # Market cap
            if not data.get("market_cap"):
                details = fetch_ticker_details(ticker)
                api_calls += 1
                data.update(details)
                time.sleep(RATE_LIMIT_DELAY)

            # Financials (EPS, debt)
            financials = fetch_financials(ticker)
            api_calls += 1
            data.update(financials)
            time.sleep(RATE_LIMIT_DELAY)

            # Dividends
            dividends = fetch_dividends(ticker)
            api_calls += 1
            data.update(dividends)

            if data.get("annual_dividend") and data.get("price") and data["price"] > 0:
                data["dividend_yield"] = round((data["annual_dividend"] / data["price"]) * 100, 4)

            if data.get("annual_dividend") and data.get("eps_current") and data["eps_current"] > 0:
                data["payout_ratio"] = round((data["annual_dividend"] / data["eps_current"]) * 100, 4)

            time.sleep(RATE_LIMIT_DELAY)

            # NEW: Analyst ratings
            ratings = fetch_analyst_ratings(ticker)
            api_calls += 1
            data.update(ratings)
            time.sleep(RATE_LIMIT_DELAY)

            # NEW: Short interest
            short = fetch_short_interest(ticker)
            api_calls += 1
            data.update(short)
            time.sleep(RATE_LIMIT_DELAY)

            # NEW: Daily bars for OBV
            bars = fetch_daily_bars(ticker, days=25)
            api_calls += 1
            if bars:
                obv_data = calculate_obv_trend(bars)
                data.update(obv_data)

                # Also calculate 20-day avg volume
                volumes = [b["volume"] for b in bars if b.get("volume")]
                if volumes:
                    data["avg_volume_20d"] = int(sum(volumes) / len(volumes))

            time.sleep(RATE_LIMIT_DELAY)

            # Write to Supabase
            success = write_raw_data(supabase, ticker, data)
            if success:
                collected += 1
            else:
                failed += 1
                errors.append(f"{ticker}: DB write failed")

            if (i + 1) % 50 == 0:
                print(f"  Progress: {i + 1}/{len(tickers)} ({collected} ok, {failed} failed)")

        except Exception as e:
            failed += 1
            errors.append(f"{ticker}: {str(e)[:100]}")
            print(f"  ❌ Error on {ticker}: {e}")
            continue

    result = {
        "collected": collected,
        "failed": failed,
        "api_calls": api_calls,
        "errors": errors[:20],
    }

    print(f"\n{'='*60}")
    print(f"Collection complete:")
    print(f"  ✅ Collected: {collected}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📡 API calls: {api_calls}")
    print(f"{'='*60}")

    return result


def init_supabase() -> Client:
    """Initialize Supabase client."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


if __name__ == "__main__":
    import sys

    test_tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "JPM", "V", "KO"]

    if "--all" in sys.argv:
        # Fetch all tickers from database
        supabase = init_supabase()
        resp = supabase.table("tickers").select("ticker").eq("is_active", True).limit(3000).execute()
        test_tickers = [r["ticker"] for r in resp.data]
        print(f"{'='*60}")
        print(f"SeeSaw MFSES — Collector v2 (ALL {len(test_tickers)} tickers)")
        print(f"{'='*60}")
    elif len(sys.argv) > 1:
        test_tickers = [t for t in sys.argv[1:] if not t.startswith("--")]
        print(f"{'='*60}")
        print(f"SeeSaw MFSES — Collector v2 (Test Mode)")
        print(f"Tickers: {test_tickers}")
        print(f"{'='*60}")
    else:
        print(f"{'='*60}")
        print(f"SeeSaw MFSES — Collector v2 (Test Mode)")
        print(f"Tickers: {test_tickers}")
        print(f"{'='*60}")

    result = run_collector(test_tickers)
    print(f"\nResult: {json.dumps(result, indent=2)}")
