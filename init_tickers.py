"""
SeeSaw MFSES — Ticker Bootstrap (Step 0 — Run Once)
=====================================================
Loads 2,501 stock tickers into Supabase.
Sets initial sectors, tiers, and Markov states (all COLD).
Fetches baseline market cap from Polygon to assign tiers.

Run this ONCE when setting up the system for the first time.
After this, the pipeline handles everything automatically.

Usage:
    python init_tickers.py                    # Load all tickers
    python init_tickers.py --tier1-only       # Load only mega caps (testing)
    python init_tickers.py --dry-run          # Preview without writing to DB
"""

import os
import sys
import json
import time
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

# Tier thresholds (market cap in USD)
TIER_THRESHOLDS = {
    1: 100_000_000_000,    # Mega: $100B+
    2: 10_000_000_000,     # Large: $10B-$100B
    3: 2_000_000_000,      # Mid: $2B-$10B
    4: 300_000_000,        # Small: $300M-$2B
}

# Sector mapping (SIC codes → clean sector names)
SECTOR_MAP = {
    "technology": "Technology",
    "software": "Technology",
    "semiconductors": "Technology",
    "electronic": "Technology",
    "computer": "Technology",
    "healthcare": "Healthcare",
    "pharmaceutical": "Healthcare",
    "biotechnology": "Healthcare",
    "medical": "Healthcare",
    "finance": "Financials",
    "banking": "Financials",
    "insurance": "Financials",
    "investment": "Financials",
    "real estate": "Real Estate",
    "reit": "Real Estate",
    "consumer": "Consumer",
    "retail": "Consumer",
    "food": "Consumer Staples",
    "beverage": "Consumer Staples",
    "household": "Consumer Staples",
    "energy": "Energy",
    "oil": "Energy",
    "gas": "Energy",
    "petroleum": "Energy",
    "industrial": "Industrials",
    "manufacturing": "Industrials",
    "aerospace": "Industrials",
    "defense": "Industrials",
    "transportation": "Industrials",
    "utility": "Utilities",
    "electric": "Utilities",
    "water": "Utilities",
    "communication": "Communication",
    "telecom": "Communication",
    "media": "Communication",
    "entertainment": "Communication",
    "material": "Materials",
    "chemical": "Materials",
    "mining": "Materials",
    "metal": "Materials",
}

# 10 GICS Sectors we use
VALID_SECTORS = [
    "Technology", "Healthcare", "Financials", "Consumer",
    "Consumer Staples", "Energy", "Industrials", "Utilities",
    "Communication", "Real Estate", "Materials",
]


# ============================================================
# CURATED SEED LIST
# ============================================================
# Core tickers guaranteed to be included (S&P 500 top holdings + key stocks).
# The rest are discovered via Polygon's ticker search API.

SEED_TICKERS = [
    # Mega Cap Tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "ORCL",
    "CRM", "ADBE", "AMD", "INTC", "CSCO", "IBM", "NOW", "QCOM", "TXN", "AMAT",
    "INTU", "MU", "LRCX", "KLAC", "SNPS", "CDNS", "MRVL", "PANW", "CRWD", "FTNT",
    "PLTR", "NET", "DDOG", "ZS", "SNOW", "TEAM", "WDAY", "SHOP", "SQ", "COIN",
    
    # Healthcare
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "AMGN",
    "BMY", "GILD", "ISRG", "VRTX", "REGN", "MDT", "SYK", "BSX", "ZTS", "CI",
    "ELV", "HCA", "MCK", "CVS", "HUM", "DXCM", "IDXX", "IQV", "MRNA", "BIIB",
    
    # Financials
    "BRK.B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "BLK",
    "C", "AXP", "SCHW", "CB", "MMC", "ICE", "CME", "PGR", "AON", "USB",
    "TFC", "AIG", "MET", "PRU", "ALL", "TRV", "AFL", "FITB", "KEY", "CFG",
    
    # Consumer Discretionary
    "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "CMG", "ABNB", "ORLY",
    "MAR", "HLT", "GM", "F", "ROST", "DHI", "LEN", "YUM", "DG", "DLTR",
    "LULU", "DECK", "ULTA", "EBAY", "ETSY", "W", "RIVN", "LCID", "DASH", "UBER",
    
    # Consumer Staples
    "PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "CL", "MDLZ", "GIS",
    "KHC", "HSY", "K", "SJM", "CAG", "CPB", "STZ", "TAP", "KDP", "MNST",
    
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "PXD", "OXY",
    "WMB", "KMI", "HAL", "DVN", "FANG", "HES", "BKR", "CTRA", "OKE", "TRGP",
    
    # Industrials
    "CAT", "GE", "HON", "UNP", "UPS", "RTX", "BA", "DE", "LMT", "NOC",
    "GD", "MMM", "ETN", "ITW", "EMR", "PH", "ROK", "FDX", "CSX", "NSC",
    "WM", "RSG", "CARR", "OTIS", "TT", "IR", "DOV", "SWK", "GWW", "FAST",
    
    # Utilities
    "NEE", "SO", "DUK", "D", "AEP", "SRE", "EXC", "XEL", "ED", "WEC",
    "ES", "AWK", "DTE", "PPL", "FE", "CEG", "VST", "AES", "CMS", "EVRG",
    
    # Communication
    "DIS", "CMCSA", "NFLX", "T", "VZ", "TMUS", "CHTR", "EA", "TTWO", "WBD",
    "PARA", "LYV", "MTCH", "RBLX", "U", "ZM", "PINS", "SNAP", "SPOT", "ROKU",
    
    # Real Estate
    "PLD", "AMT", "CCI", "EQIX", "PSA", "SPG", "O", "DLR", "WELL", "AVB",
    "EQR", "VTR", "ARE", "MAA", "UDR", "ESS", "CPT", "INVH", "PEAK", "KIM",
    
    # Materials
    "LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "DOW", "DD", "VMC",
    "MLM", "PPG", "ALB", "CF", "MOS", "IFF", "CE", "EMN", "PKG", "IP",
]


# ============================================================
# POLYGON API HELPERS
# ============================================================

def fetch_all_tickers(min_market_cap: int = 300_000_000) -> list[dict]:
    """
    Fetch all US stock tickers from Polygon that meet our criteria.
    Uses the Tickers v3 endpoint with pagination.
    """
    all_tickers = []
    url = f"{POLYGON_BASE}/v3/reference/tickers"
    params = {
        "market": "stocks",
        "exchange": "XNAS,XNYS",  # NASDAQ + NYSE
        "type": "CS",              # Common Stock only
        "active": "true",
        "limit": 1000,
        "apiKey": POLYGON_API_KEY,
    }
    
    page = 0
    while url:
        resp = requests.get(url, params=params if page == 0 else None, timeout=30)
        if resp.status_code != 200:
            print(f"  ⚠️  HTTP {resp.status_code} fetching tickers")
            break
        
        data = resp.json()
        results = data.get("results", [])
        all_tickers.extend(results)
        
        # Pagination
        next_url = data.get("next_url")
        if next_url:
            url = f"{next_url}&apiKey={POLYGON_API_KEY}"
            page += 1
            time.sleep(0.25)  # Rate limit
        else:
            url = None
        
        print(f"  Fetched {len(all_tickers)} tickers so far (page {page})...")
    
    return all_tickers


def classify_sector(sic_description: str | None) -> str:
    """Map SIC description to one of our 10 sectors."""
    if not sic_description:
        return "Unknown"
    
    desc_lower = sic_description.lower()
    for keyword, sector in SECTOR_MAP.items():
        if keyword in desc_lower:
            return sector
    
    return "Unknown"


def classify_tier(market_cap: int | None) -> int:
    """Assign tier based on market cap."""
    if not market_cap or market_cap <= 0:
        return 4  # Default to small cap
    
    for tier, threshold in sorted(TIER_THRESHOLDS.items()):
        if market_cap >= threshold:
            best_tier = tier
    
    # Re-check in order (largest first)
    if market_cap >= TIER_THRESHOLDS[1]:
        return 1
    elif market_cap >= TIER_THRESHOLDS[2]:
        return 2
    elif market_cap >= TIER_THRESHOLDS[3]:
        return 3
    else:
        return 4


# ============================================================
# MAIN BOOTSTRAP
# ============================================================

def run_bootstrap(tier1_only: bool = False, dry_run: bool = False) -> dict:
    """
    Main entry point. Loads tickers into Supabase.
    
    1. Start with seed list (curated top stocks)
    2. Fetch all US stocks from Polygon
    3. Filter by market cap > $300M
    4. Classify sector and tier
    5. Insert into Supabase (tickers + stock_states tables)
    """
    if not POLYGON_API_KEY:
        raise ValueError("Missing POLYGON_API_KEY")
    
    print(f"{'='*60}")
    print(f"SeeSaw MFSES — Ticker Bootstrap")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}")
    
    # --- Step 1: Fetch all tickers from Polygon ---
    print(f"\n📡 Fetching all US stock tickers from Polygon...")
    
    if tier1_only:
        # Just use seed list for testing
        raw_tickers = [{"ticker": t} for t in SEED_TICKERS]
        print(f"  Using seed list only ({len(raw_tickers)} tickers)")
    else:
        raw_tickers = fetch_all_tickers()
        print(f"  Found {len(raw_tickers)} total US stocks")
    
    # --- Step 2: Enrich with market cap and classify ---
    print(f"\n🏷️  Classifying tickers...")
    
    ticker_records = []
    seen = set()
    
    # Process seed tickers first (guaranteed inclusion)
    for t in SEED_TICKERS:
        if t not in seen:
            seen.add(t)
            ticker_records.append({
                "ticker": t,
                "company_name": t,  # Will be enriched below
                "sector": "Unknown",
                "tier": 2,  # Default, will be updated
                "is_active": True,
            })
    
    # Process Polygon results
    for raw in raw_tickers:
        t = raw.get("ticker", "")
        if not t or t in seen:
            continue
        if "." in t and not t.endswith(".B"):
            continue  # Skip weird share classes (except BRK.B etc)
        if len(t) > 5:
            continue  # Skip warrants, units, etc.
        
        seen.add(t)
        
        sector = classify_sector(raw.get("sic_description"))
        market_cap = raw.get("market_cap", 0)
        tier = classify_tier(market_cap)
        
        ticker_records.append({
            "ticker": t,
            "company_name": raw.get("name", t),
            "sector": sector,
            "industry": raw.get("sic_description"),
            "tier": tier,
            "market_cap": market_cap if market_cap else None,
            "is_active": True,
        })
    
    # --- Step 3: Trim to 2,501 (prioritize by tier + seed status) ---
    # Seed tickers always included, then fill by market cap
    seed_set = set(SEED_TICKERS)
    seed_records = [r for r in ticker_records if r["ticker"] in seed_set]
    other_records = [r for r in ticker_records if r["ticker"] not in seed_set]
    
    # Sort others by market cap descending (largest first)
    other_records.sort(key=lambda x: x.get("market_cap") or 0, reverse=True)
    
    remaining_slots = 2501 - len(seed_records)
    final_records = seed_records + other_records[:remaining_slots]
    
    print(f"  Final count: {len(final_records)} tickers")
    
    # Count by tier
    tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    sector_counts = {}
    for r in final_records:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1
        sector_counts[r["sector"]] = sector_counts.get(r["sector"], 0) + 1
    
    print(f"\n  By Tier:")
    print(f"    Tier 1 (Mega $100B+):  {tier_counts[1]}")
    print(f"    Tier 2 (Large $10B+):  {tier_counts[2]}")
    print(f"    Tier 3 (Mid $2B+):     {tier_counts[3]}")
    print(f"    Tier 4 (Small $300M+): {tier_counts[4]}")
    
    print(f"\n  By Sector:")
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
        print(f"    {sector}: {count}")
    
    if dry_run:
        print(f"\n🏁 DRY RUN — no database writes.")
        return {"total": len(final_records), "tiers": tier_counts, "sectors": sector_counts}
    
    # --- Step 4: Write to Supabase ---
    print(f"\n💾 Writing to Supabase...")
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    
    # Batch insert tickers
    inserted = 0
    for i in range(0, len(final_records), 100):
        batch = final_records[i:i + 100]
        try:
            supabase.table("tickers") \
                .upsert(batch, on_conflict="ticker") \
                .execute()
            inserted += len(batch)
            print(f"  Inserted {inserted}/{len(final_records)} tickers...")
        except Exception as e:
            print(f"  ❌ Batch insert failed: {e}")
            # Try one at a time
            for r in batch:
                try:
                    supabase.table("tickers") \
                        .upsert(r, on_conflict="ticker") \
                        .execute()
                    inserted += 1
                except Exception as e2:
                    print(f"    ❌ {r['ticker']}: {e2}")
    
    # --- Step 5: Initialize Markov states (all COLD) ---
    print(f"\n🎲 Initializing Markov states...")
    
    now = datetime.now(timezone.utc)
    state_records = []
    for r in final_records:
        state_records.append({
            "ticker": r["ticker"],
            "current_state": "COLD",
            "last_updated": now.isoformat(),
            "next_update_due": now.isoformat(),  # Due immediately for first run
        })
    
    states_inserted = 0
    for i in range(0, len(state_records), 100):
        batch = state_records[i:i + 100]
        try:
            supabase.table("stock_states") \
                .upsert(batch, on_conflict="ticker") \
                .execute()
            states_inserted += len(batch)
        except Exception as e:
            print(f"  ❌ State batch failed: {e}")
    
    print(f"  ✅ {states_inserted} Markov states initialized (all COLD, due NOW)")
    
    # --- Step 6: Initialize empty raw_data and scores rows ---
    print(f"\n📊 Initializing empty score rows...")
    
    raw_records = [{"ticker": r["ticker"]} for r in final_records]
    score_records = [{"ticker": r["ticker"], "sentiment_score": 12} for r in final_records]
    
    for i in range(0, len(raw_records), 100):
        try:
            supabase.table("stock_raw_data") \
                .upsert(raw_records[i:i+100], on_conflict="ticker") \
                .execute()
        except Exception:
            pass
    
    for i in range(0, len(score_records), 100):
        try:
            supabase.table("stock_scores") \
                .upsert(score_records[i:i+100], on_conflict="ticker") \
                .execute()
        except Exception:
            pass
    
    print(f"  ✅ Empty rows created")
    
    result = {
        "total": len(final_records),
        "inserted": inserted,
        "states_initialized": states_inserted,
        "tiers": tier_counts,
        "sectors": sector_counts,
    }
    
    print(f"\n{'='*60}")
    print(f"✅ Bootstrap complete!")
    print(f"   {inserted} tickers loaded")
    print(f"   {states_inserted} Markov states initialized")
    print(f"   All stocks set to COLD, due for immediate update")
    print(f"   Next: Run the pipeline (collector → scorer → state_updater)")
    print(f"{'='*60}")
    
    return result


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    tier1_only = "--tier1-only" in sys.argv
    dry_run = "--dry-run" in sys.argv
    
    run_bootstrap(tier1_only=tier1_only, dry_run=dry_run)
