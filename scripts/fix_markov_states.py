"""
Quick script to re-evaluate markov states for all tickers based on current data.
This will read volume_ratio, price_change_pct from the database and update states.
"""

import os
from dotenv import load_dotenv
from supabase import create_client

# Load .env from parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://isnuktzlqeeivhbwykxs.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_KEY:
    print("Error: SUPABASE_SERVICE_ROLE_KEY environment variable not set")
    print("Using anon key from dashboard for read-only testing...")
    SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzbnVrdHpscWVlaXZoYnd5a3hzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzAwODMwODYsImV4cCI6MjA4NTY1OTA4Nn0.3u6IDfRFChaHyQ3yIharGHaVicNjgJAaPvX-vGr2N3Q"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Fetch all stocks with their current data
print("Fetching stock data...")
result = supabase.table("stock_raw_data") \
    .select("ticker, volume_ratio, price_change_pct") \
    .limit(3000) \
    .execute()

stocks = result.data
print(f"Found {len(stocks)} stocks")

# Classify by activity level
hot = []
warm = []
cold = []
frozen = []

for stock in stocks:
    ticker = stock['ticker']
    vol_ratio = stock.get('volume_ratio') or 1.0
    price_chg = abs(stock.get('price_change_pct') or 0)

    # Classify based on activity
    if vol_ratio >= 2.0 or price_chg >= 5.0:
        hot.append(ticker)
    elif vol_ratio >= 1.5 or price_chg >= 3.0:
        warm.append(ticker)
    elif vol_ratio < 0.5 and price_chg < 0.5:
        frozen.append(ticker)
    else:
        cold.append(ticker)

print(f"\nClassification results:")
print(f"  HOT:    {len(hot)} stocks")
print(f"  WARM:   {len(warm)} stocks")
print(f"  COLD:   {len(cold)} stocks")
print(f"  FROZEN: {len(frozen)} stocks")

if hot:
    print(f"\n  Top 10 HOT: {hot[:10]}")
if warm:
    print(f"  Top 10 WARM: {warm[:10]}")

print("\nTo update the database, you need the service role key.")
print("Run: python scripts/markov.py to properly initialize states")
