"""
SeeSaw MFSES — Collector (Step 2 of Pipeline)
================================================
Receives ticker list from Markov Prioritizer (Step 1).
Fetches price, volume, fundamentals, and dividend data from Polygon.io API.
Writes raw data to Supabase stock_raw_data table.
Respects caching — skips fundamentals if cached < 24hrs old.

Runs: Called by n8n after markov.py returns the batch list.
API: Polygon.io (free tier = 5/min, paid = unlimited)
"""

import os
import json
import time
import math
import requests
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

# ============================================================
# CONFIG
# ============================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY")

POLYGON_BASE = "https://api.polygon.io"

# Batching config
SNAPSHOT_BATCH_SIZE = 100      # Polygon supports up to ~100 tickers per snapshot call
RATE_LIMIT_DELAY = 0.25        # Seconds between API calls (adjust for your plan)
FUNDAMENTALS_CACHE_HOURS = 24  # Skip fundamentals fetch if cached within this window
DIVIDEND_CACHE_HOURS = 24      # Skip dividend fetch if cached within this window

# Retry config
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


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
                # Rate limited — back off
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
            print(f"  ⚠️  Timeout for {url}, attempt {attempt + 1}/{MAX_RETRIES}")
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
    """
    Fetch current price + volume for multiple tickers using Polygon Snapshot API.
    Batches into groups of 100 for efficiency.
    
    Returns: {ticker: {price, prev_close, change_pct, volume, market_cap, ...}}
    """
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
                
                # Calculate change %
                change_pct = 0.0
                if prev_close and prev_close > 0:
                    change_pct = round(((price - prev_close) / prev_close) * 100, 4)
                
                results[t] = {
                    "price": price,
                    "previous_close": prev_close,
                    "price_change_pct": change_pct,
                    "volume": int(volume) if volume else 0,
                    "market_cap": snap.get("market_cap"),  # May not be in snapshot
                }
        
        # Rate limiting between batches
        if batch_num < len(batches) - 1:
            time.sleep(RATE_LIMIT_DELAY)
    
    return results


def fetch_ticker_details(ticker: str) -> dict:
    """
    Fetch detailed info for a single ticker (market cap, shares outstanding, etc).
    Uses Polygon Ticker Details v3 endpoint.
    """
    url = f"{POLYGON_BASE}/v3/reference/tickers/{ticker}"
    data = _api_get(url)
    
    if data and "results" in data:
        r = data["results"]
        return {
            "market_cap": r.get("market_cap"),
            "shares_outstanding": r.get("share_class_shares_outstanding") or r.get("weighted_shares_outstanding"),
            "company_name": r.get("name", ticker),
            "sector": r.get("sic_description", "Unknown"),
        }
    return {}


def fetch_financials(ticker: str) -> dict:
    """
    Fetch latest financial data (EPS, debt, equity) from Polygon Financials API.
    Uses the most recent quarterly filing.
    """
    url = f"{POLYGON_BASE}/vX/reference/financials"
    params = {
        "ticker": ticker,
        "limit": 5,           # Last 5 filings
        "sort": "period_of_report_date",
        "order": "desc",
        "timeframe": "quarterly",
    }
    
    data = _api_get(url, params)
    
    if not data or "results" not in data or not data["results"]:
        return {}
    
    result = {}
    filings = data["results"]
    
    # Latest filing
    latest = filings[0]
    income = latest.get("financials", {}).get("income_statement", {})
    balance = latest.get("financials", {}).get("balance_sheet", {})
    
    # --- EPS ---
    # Try diluted EPS first, then basic
    eps_data = income.get("diluted_earnings_per_share") or income.get("basic_earnings_per_share")
    if eps_data:
        result["eps_current"] = eps_data.get("value", 0)
    
    # EPS from ~4 quarters ago for YoY growth
    if len(filings) >= 5:
        old_income = filings[4].get("financials", {}).get("income_statement", {})
        old_eps = old_income.get("diluted_earnings_per_share") or old_income.get("basic_earnings_per_share")
        if old_eps:
            result["eps_1y_ago"] = old_eps.get("value", 0)
    
    # Calculate EPS growth rate
    eps_current = result.get("eps_current", 0)
    eps_old = result.get("eps_1y_ago")
    if eps_old and eps_old != 0:
        result["eps_growth_rate"] = round(((eps_current - eps_old) / abs(eps_old)) * 100, 4)
    
    # --- Balance Sheet ---
    # Total debt
    long_debt = balance.get("long_term_debt", {}).get("value", 0) or 0
    short_debt = balance.get("current_debt", {}).get("value", 0) or \
                 balance.get("short_term_debt", {}).get("value", 0) or 0
    total_debt = long_debt + short_debt
    result["total_debt"] = int(total_debt)
    
    # Shareholders equity
    equity = balance.get("equity", {}).get("value") or \
             balance.get("stockholders_equity", {}).get("value") or \
             balance.get("equity_attributable_to_parent", {}).get("value")
    
    if equity is not None:
        result["shareholders_equity"] = int(equity)
        if equity != 0:
            result["debt_to_equity"] = round(total_debt / abs(equity), 4)
        else:
            result["debt_to_equity"] = 99.99  # Flag: zero equity
    
    return result


def fetch_dividends(ticker: str) -> dict:
    """
    Fetch dividend data from Polygon Dividends API.
    Calculates annual dividend, yield, and consecutive increases.
    """
    url = f"{POLYGON_BASE}/v3/reference/dividends"
    params = {
        "ticker": ticker,
        "limit": 20,       # ~5 years of quarterly dividends
        "order": "desc",
        "sort": "ex_dividend_date",
    }
    
    data = _api_get(url, params)
    
    if not data or "results" not in data or not data["results"]:
        return {"annual_dividend": 0, "dividend_yield": 0}
    
    divs = data["results"]
    result = {}
    
    # Most recent ex-dividend date
    result["ex_dividend_date"] = divs[0].get("ex_dividend_date")
    
    # Calculate annual dividend (sum of last 4 quarterly dividends)
    recent_divs = []
    for d in divs[:4]:  # Last 4 payments
        amt = d.get("cash_amount", 0)
        if amt and amt > 0:
            recent_divs.append(amt)
    
    annual_dividend = sum(recent_divs)
    result["annual_dividend"] = round(annual_dividend, 4)
    
    # Calculate 5-year growth rate
    if len(divs) >= 8:
        # Sum of 4 most recent vs 4 from ~4-5 years ago
        recent_annual = sum(d.get("cash_amount", 0) for d in divs[:4])
        old_annual = sum(d.get("cash_amount", 0) for d in divs[-4:])
        
        if old_annual > 0:
            years = min(len(divs) // 4, 5)  # Approximate years of data
            if years > 0:
                growth = ((recent_annual / old_annual) ** (1 / years) - 1) * 100
                result["dividend_growth_5yr"] = round(growth, 4)
    
    # Count consecutive years of increases (simplified)
    # Group dividends by year, check if each year > previous
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


# ============================================================
# CACHE CHECKING
# ============================================================

def get_cache_status(supabase: Client, tickers: list[str]) -> dict:
    """
    Check which tickers have fresh enough cached data to skip certain fetches.
    Returns: {ticker: {"skip_fundamentals": bool, "skip_dividends": bool}}
    """
    result = supabase.table("stock_raw_data") \
        .select("ticker, last_fundamental_update, last_dividend_update") \
        .in_("ticker", tickers) \
        .execute()
    
    cache = {}
    now = datetime.now(timezone.utc)
    fund_cutoff = now - timedelta(hours=FUNDAMENTALS_CACHE_HOURS)
    div_cutoff = now - timedelta(hours=DIVIDEND_CACHE_HOURS)
    
    for row in (result.data or []):
        t = row["ticker"]
        
        skip_fund = False
        skip_div = False
        
        if row.get("last_fundamental_update"):
            try:
                last_fund = datetime.fromisoformat(row["last_fundamental_update"].replace("Z", "+00:00"))
                skip_fund = last_fund > fund_cutoff
            except (ValueError, TypeError):
                pass
        
        if row.get("last_dividend_update"):
            try:
                last_div = datetime.fromisoformat(row["last_dividend_update"].replace("Z", "+00:00"))
                skip_div = last_div > div_cutoff
            except (ValueError, TypeError):
                pass
        
        cache[t] = {"skip_fundamentals": skip_fund, "skip_dividends": skip_div}
    
    return cache


# ============================================================
# VOLUME AVERAGE CALCULATOR
# ============================================================

def fetch_volume_history(ticker: str) -> int | None:
    """
    Fetch 20-day average volume for a ticker using Polygon Aggregates.
    Returns the average daily volume, or None if unavailable.
    """
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    
    url = f"{POLYGON_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
    params = {"adjusted": "true", "sort": "desc", "limit": 20}
    
    data = _api_get(url, params)
    
    if data and "results" in data and data["results"]:
        volumes = [bar["v"] for bar in data["results"] if "v" in bar]
        if volumes:
            return int(sum(volumes) / len(volumes))
    
    return None


# ============================================================
# MAIN WRITE TO SUPABASE
# ============================================================

def write_raw_data(supabase: Client, ticker: str, data: dict) -> bool:
    """
    Upsert raw data for a single ticker into stock_raw_data table.
    Returns True on success.
    """
    now = datetime.now(timezone.utc).isoformat()
    
    record = {
        "ticker": ticker,
        "collected_at": now,
    }
    
    # Price & volume (always fresh)
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
        # Calculate volume ratio
        if data.get("volume") and data["avg_volume_20d"] > 0:
            record["volume_ratio"] = round(data["volume"] / data["avg_volume_20d"], 3)
    
    # Earnings (cached)
    if "eps_current" in data:
        record["eps_current"] = data["eps_current"]
        record["last_fundamental_update"] = now
    if "eps_1y_ago" in data:
        record["eps_1y_ago"] = data["eps_1y_ago"]
    if "eps_growth_rate" in data:
        record["eps_growth_rate"] = data["eps_growth_rate"]
    
    # Balance sheet (cached)
    if "total_debt" in data:
        record["total_debt"] = data["total_debt"]
    if "shareholders_equity" in data:
        record["shareholders_equity"] = data["shareholders_equity"]
    if "debt_to_equity" in data:
        record["debt_to_equity"] = data["debt_to_equity"]
    
    # Dividends (cached)
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
    
    # 52-week range
    if "fifty_two_week_high" in data:
        record["fifty_two_week_high"] = data["fifty_two_week_high"]
    if "fifty_two_week_low" in data:
        record["fifty_two_week_low"] = data["fifty_two_week_low"]
    
    # Data quality score
    quality_checks = 0
    if data.get("price") and data["price"] > 0: quality_checks += 1
    if data.get("market_cap") and data["market_cap"] > 0: quality_checks += 1
    if data.get("eps_current") is not None: quality_checks += 1
    if data.get("debt_to_equity") is not None: quality_checks += 1
    if data.get("volume") and data["volume"] > 0: quality_checks += 1
    record["data_quality_score"] = int((quality_checks / 5) * 100)
    
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
    Main entry point. Called by n8n after markov.py.
    
    Args:
        tickers: List of ticker symbols to fetch data for.
    
    Returns:
        {
            "collected": 47,
            "failed": 3,
            "skipped_fundamentals": 30,
            "skipped_dividends": 35,
            "api_calls": 12,
            "errors": ["BADTICKER: no data found", ...]
        }
    """
    if not tickers:
        return {"collected": 0, "failed": 0, "api_calls": 0, "errors": []}
    
    if not POLYGON_API_KEY:
        raise ValueError("Missing POLYGON_API_KEY environment variable")
    
    supabase = init_supabase()
    
    # Track stats
    collected = 0
    failed = 0
    api_calls = 0
    errors = []
    skipped_fund = 0
    skipped_div = 0
    
    # --- STEP A: Batch fetch prices + volume (fast, ~1 call per 100 tickers) ---
    print(f"📡 Fetching snapshots for {len(tickers)} tickers...")
    snapshots = fetch_snapshots(tickers)
    api_calls += math.ceil(len(tickers) / SNAPSHOT_BATCH_SIZE)
    print(f"  ✅ Got {len(snapshots)} snapshots")
    
    # --- STEP B: Check cache to avoid redundant API calls ---
    cache_status = get_cache_status(supabase, tickers)
    
    # --- STEP C: Per-ticker enrichment (fundamentals + dividends) ---
    for i, ticker in enumerate(tickers):
        try:
            # Start with snapshot data
            data = snapshots.get(ticker, {})
            
            if not data or not data.get("price"):
                # No snapshot data — try ticker details as fallback
                details = fetch_ticker_details(ticker)
                api_calls += 1
                time.sleep(RATE_LIMIT_DELAY)
                
                if not details:
                    errors.append(f"{ticker}: no snapshot or details found")
                    failed += 1
                    continue
                
                data.update(details)
            
            # Get market cap + shares outstanding if not in snapshot
            if not data.get("market_cap"):
                details = fetch_ticker_details(ticker)
                api_calls += 1
                data.update(details)
                time.sleep(RATE_LIMIT_DELAY)
            
            # --- Fundamentals (cached) ---
            cache = cache_status.get(ticker, {})
            
            if not cache.get("skip_fundamentals"):
                financials = fetch_financials(ticker)
                api_calls += 1
                data.update(financials)
                time.sleep(RATE_LIMIT_DELAY)
            else:
                skipped_fund += 1
            
            # --- Dividends (cached) ---
            if not cache.get("skip_dividends"):
                dividends = fetch_dividends(ticker)
                api_calls += 1
                data.update(dividends)
                
                # Calculate yield and payout ratio
                if data.get("annual_dividend") and data.get("price") and data["price"] > 0:
                    data["dividend_yield"] = round((data["annual_dividend"] / data["price"]) * 100, 4)
                
                if data.get("annual_dividend") and data.get("eps_current") and data["eps_current"] > 0:
                    data["payout_ratio"] = round((data["annual_dividend"] / data["eps_current"]) * 100, 4)
                
                time.sleep(RATE_LIMIT_DELAY)
            else:
                skipped_div += 1
            
            # --- 20-day avg volume (only if we don't have it cached) ---
            if not cache_status.get(ticker, {}).get("skip_fundamentals"):
                avg_vol = fetch_volume_history(ticker)
                if avg_vol:
                    data["avg_volume_20d"] = avg_vol
                api_calls += 1
                time.sleep(RATE_LIMIT_DELAY)
            
            # --- Write to Supabase ---
            success = write_raw_data(supabase, ticker, data)
            if success:
                collected += 1
            else:
                failed += 1
                errors.append(f"{ticker}: DB write failed")
            
            # Progress logging
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
        "skipped_fundamentals": skipped_fund,
        "skipped_dividends": skipped_div,
        "api_calls": api_calls,
        "errors": errors[:20],  # Cap error list
    }
    
    print(f"\n{'='*60}")
    print(f"Collection complete:")
    print(f"  ✅ Collected: {collected}")
    print(f"  ❌ Failed: {failed}")
    print(f"  ⏭️  Skipped fundamentals (cached): {skipped_fund}")
    print(f"  ⏭️  Skipped dividends (cached): {skipped_div}")
    print(f"  📡 API calls: {api_calls}")
    print(f"{'='*60}")
    
    return result


def init_supabase() -> Client:
    """Initialize Supabase client."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ============================================================
# STANDALONE EXECUTION (for testing)
# ============================================================

if __name__ == "__main__":
    import sys
    
    # Test with a small list
    test_tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "BRK.B", "JPM", "V"]
    
    if len(sys.argv) > 1:
        test_tickers = sys.argv[1:]
    
    print(f"{'='*60}")
    print(f"SeeSaw MFSES — Collector (Test Mode)")
    print(f"Tickers: {test_tickers}")
    print(f"{'='*60}")
    
    result = run_collector(test_tickers)
    print(f"\nResult: {json.dumps(result, indent=2)}")
