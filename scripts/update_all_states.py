"""
Update all markov states based on current stock data.
"""

import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client

# Load .env from parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env file")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

print("Fetching all stocks from dashboard_stocks...")
# Supabase caps at 1000 rows per request, so paginate
stocks = []
page_size = 1000
offset = 0
while True:
    result = supabase.table("dashboard_stocks") \
        .select("ticker, volume_ratio, price_change_pct") \
        .range(offset, offset + page_size - 1) \
        .execute()
    stocks.extend(result.data)
    if len(result.data) < page_size:
        break
    offset += page_size
print(f"Found {len(stocks)} stocks\n")

# Classify stocks
updates = []
stats = {"HOT": 0, "WARM": 0, "COLD": 0, "FROZEN": 0}

for stock in stocks:
    ticker = stock['ticker']
    vol_ratio = stock.get('volume_ratio') or 1.0
    price_chg = abs(stock.get('price_change_pct') or 0)

    # Determine state based on activity
    if vol_ratio >= 2.0 or price_chg >= 5.0:
        state = "HOT"
        interval_min = 30
        reason = f"vol:{vol_ratio:.1f}x chg:{price_chg:.1f}%"
    elif vol_ratio >= 1.5 or price_chg >= 3.0:
        state = "WARM"
        interval_min = 120
        reason = f"vol:{vol_ratio:.1f}x chg:{price_chg:.1f}%"
    elif vol_ratio < 0.5 and price_chg < 0.5:
        state = "FROZEN"
        interval_min = 1440
        reason = "low_activity"
    else:
        state = "COLD"
        interval_min = 360
        reason = "normal"

    stats[state] += 1

    now = datetime.now(timezone.utc)
    next_update = now + timedelta(minutes=interval_min)

    updates.append({
        "ticker": ticker,
        "current_state": state,
        "last_updated": now.isoformat(),
        "next_update_due": next_update.isoformat(),
        "promotion_reason": reason,
        "consecutive_hot": 1 if state == "HOT" else 0,
    })

print(f"State distribution:")
print(f"  HOT:    {stats['HOT']:4d} stocks")
print(f"  WARM:   {stats['WARM']:4d} stocks")
print(f"  COLD:   {stats['COLD']:4d} stocks")
print(f"  FROZEN: {stats['FROZEN']:4d} stocks")

print(f"\nUpdating {len(updates)} states in database...")

# Batch update in chunks of 100
batch_size = 100
for i in range(0, len(updates), batch_size):
    batch = updates[i:i+batch_size]
    supabase.table("stock_states").upsert(batch).execute()
    print(f"  Processed {min(i+batch_size, len(updates))}/{len(updates)} stocks")

print("\nDone! Refresh your dashboard to see the updated states.")
