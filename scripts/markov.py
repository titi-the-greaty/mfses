"""
SeeSaw MFSES — Markov Prioritizer (Step 1 of Pipeline)
=======================================================
Reads current Markov states from Supabase.
Determines which stocks are DUE for an update this cycle.
Evaluates transition signals for stocks with fresh data.
Outputs a prioritized batch list for the collector.

Runs: Every 30 minutes during market hours (via n8n → Supabase Edge Function)
Also: Daily 6AM ET full refresh (overrides Markov, updates all 2,501)
"""

import os
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

# Load .env from parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# ============================================================
# CONFIG
# ============================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# Markov state → update interval in minutes
STATE_INTERVALS = {
    "HOT":    30,
    "WARM":   120,
    "COLD":   360,
    "FROZEN": 1440,
}

# Maximum tickers per cycle (prevent runaway API usage)
MAX_TICKERS_PER_CYCLE = 500

# Promotion expiry (HOT status lasts max 24 hours before re-evaluation)
PROMOTION_EXPIRY_HOURS = 24


# ============================================================
# TRANSITION THRESHOLDS
# ============================================================
# These determine when a stock moves between states.

TRANSITIONS = {
    # Volume-based triggers
    "volume_spike_extreme": {"threshold": 3.0, "boost": 0.40, "target": "HOT",    "reason": "volume_spike_3x"},
    "volume_spike_high":    {"threshold": 2.0, "boost": 0.30, "target": "HOT",    "reason": "volume_spike_2x"},
    "volume_spike_moderate":{"threshold": 1.5, "boost": 0.20, "target": "WARM",   "reason": "volume_spike_1.5x"},
    "volume_dead":          {"threshold": 0.5, "boost": 0.20, "target": "FROZEN", "reason": "low_volume"},
    
    # Price-based triggers
    "price_swing_large":    {"threshold": 5.0, "boost": 0.30, "target": "HOT",    "reason": "price_swing_5pct"},
    "price_swing_moderate": {"threshold": 3.0, "boost": 0.20, "target": "HOT",    "reason": "price_swing_3pct"},
    "price_flat":           {"threshold": 0.5, "boost": 0.10, "target": "COLD",   "reason": "price_flat"},
    
    # Score change triggers
    "score_jump":           {"threshold": 5,   "boost": 0.25, "target": "HOT",    "reason": "mfses_score_jump"},
}

# State priority order (for resolving which direction to move)
STATE_PRIORITY = {"HOT": 4, "WARM": 3, "COLD": 2, "FROZEN": 1}


# ============================================================
# CORE FUNCTIONS
# ============================================================

def init_supabase() -> Client:
    """Initialize Supabase client with service role key (full access)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def get_tickers_due(supabase: Client, force_all: bool = False) -> list[dict]:
    """
    Get tickers that are due for an update based on their Markov state.
    
    If force_all=True (daily full refresh), returns ALL active tickers.
    Otherwise, returns only tickers where now() >= next_update_due.
    """
    if force_all:
        # Daily full refresh — ignore Markov, get everything
        result = supabase.table("stock_states") \
            .select("ticker, current_state, last_updated") \
            .order("current_state") \
            .execute()
        return result.data
    
    # Normal cycle — only get tickers that are due
    now = datetime.now(timezone.utc).isoformat()
    result = supabase.table("stock_states") \
        .select("ticker, current_state, last_updated") \
        .lte("next_update_due", now) \
        .order("next_update_due") \
        .limit(MAX_TICKERS_PER_CYCLE) \
        .execute()

    return result.data if result.data else []


def evaluate_transitions(supabase: Client, tickers: list[str]) -> dict:
    """
    For tickers that have FRESH data (just collected), evaluate whether
    they should transition to a different Markov state.
    
    Returns dict: {ticker: {"new_state": "HOT", "reason": "volume_spike_3x"}}
    """
    if not tickers:
        return {}
    
    # Fetch raw data for these tickers
    result = supabase.table("stock_raw_data") \
        .select("ticker, volume_ratio, price_change_pct") \
        .in_("ticker", tickers) \
        .execute()
    
    # Fetch current states
    states_result = supabase.table("stock_states") \
        .select("ticker, current_state, promotion_expires, consecutive_hot") \
        .in_("ticker", tickers) \
        .execute()
    
    current_states = {s["ticker"]: s for s in states_result.data}
    transitions = {}
    
    for stock in result.data:
        ticker = stock["ticker"]
        state_info = current_states.get(ticker, {})
        current_state = state_info.get("current_state", "COLD")
        
        volume_ratio = stock.get("volume_ratio") or 1.0
        price_change = abs(stock.get("price_change_pct") or 0)

        # Calculate transition probabilities
        hot_prob = 0.0
        warm_prob = 0.0
        cold_prob = 0.0
        frozen_prob = 0.0
        best_reason = None

        # --- Volume signals ---
        if volume_ratio > 3.0:
            hot_prob += 0.40
            best_reason = "volume_spike_3x"
        elif volume_ratio > 2.0:
            hot_prob += 0.30
            best_reason = "volume_spike_2x"
        elif volume_ratio > 1.5:
            warm_prob += 0.20
            if not best_reason:
                best_reason = "volume_spike_1.5x"
        elif volume_ratio < 0.5:
            frozen_prob += 0.20
            if not best_reason:
                best_reason = "low_volume"

        # --- Price signals ---
        if price_change > 5.0:
            hot_prob += 0.30
            best_reason = best_reason or "price_swing_5pct"
        elif price_change > 3.0:
            hot_prob += 0.20
            best_reason = best_reason or "price_swing_3pct"
        elif price_change < 0.5:
            cold_prob += 0.10
        
        # --- Determine new state ---
        new_state = _resolve_new_state(
            current_state=current_state,
            hot_prob=hot_prob,
            warm_prob=warm_prob,
            cold_prob=cold_prob,
            frozen_prob=frozen_prob,
            state_info=state_info
        )
        
        if new_state != current_state:
            transitions[ticker] = {
                "new_state": new_state,
                "reason": best_reason or "natural_decay",
            }
    
    return transitions


def _resolve_new_state(
    current_state: str,
    hot_prob: float,
    warm_prob: float,
    cold_prob: float,
    frozen_prob: float,
    state_info: dict
) -> str:
    """
    Resolve which state a stock should transition to based on probabilities.
    
    Rules:
    - HOT probability > 0.3 → promote to HOT
    - HOT probability > 0.15 → promote to WARM (if currently COLD/FROZEN)
    - Frozen probability > 0.15 → demote to FROZEN (if no hot/warm signals)
    - Cold probability > 0.1 and no hot signals → demote to COLD
    - Stocks that have been HOT for 48+ consecutive cycles decay to WARM
    - Expired promotions decay one level
    """
    consecutive_hot = state_info.get("consecutive_hot", 0)
    promotion_expires = state_info.get("promotion_expires")
    
    # Check if forced promotion has expired
    if promotion_expires:
        try:
            exp_time = datetime.fromisoformat(promotion_expires.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_time:
                # Promotion expired — decay one level
                if current_state == "HOT":
                    return "WARM"
                elif current_state == "WARM":
                    return "COLD"
        except (ValueError, TypeError):
            pass
    
    # HOT fatigue — been HOT too long without fresh signals
    if current_state == "HOT" and consecutive_hot > 48 and hot_prob < 0.2:
        return "WARM"
    
    # Strong HOT signal
    if hot_prob >= 0.30:
        return "HOT"
    
    # Moderate signal — promote toward WARM
    if hot_prob >= 0.15 or warm_prob >= 0.20:
        if current_state in ("COLD", "FROZEN"):
            return "WARM"
        return current_state  # Already WARM or HOT, stay
    
    # Frozen signal with no upward pressure
    if frozen_prob >= 0.15 and hot_prob < 0.1 and warm_prob < 0.1:
        if current_state in ("COLD", "WARM"):
            return "FROZEN" if current_state == "COLD" else "COLD"
        return current_state
    
    # Cold signal
    if cold_prob >= 0.10 and hot_prob < 0.1:
        if current_state == "WARM":
            return "COLD"
        return current_state
    
    # No strong signals — natural decay over time
    # (stocks slowly cool down if nothing is happening)
    if hot_prob < 0.05 and warm_prob < 0.05:
        if current_state == "HOT" and consecutive_hot > 6:
            return "WARM"
    
    return current_state


def apply_transitions(supabase: Client, transitions: dict) -> tuple[int, int]:
    """
    Apply state transitions to the database.
    Returns (promotions_count, demotions_count).
    """
    promotions = 0
    demotions = 0
    
    for ticker, change in transitions.items():
        new_state = change["new_state"]
        reason = change["reason"]
        
        # Get current state to determine if promotion or demotion
        current = supabase.table("stock_states") \
            .select("current_state") \
            .eq("ticker", ticker) \
            .single() \
            .execute()
        
        if current.data:
            old_priority = STATE_PRIORITY.get(current.data["current_state"], 2)
            new_priority = STATE_PRIORITY.get(new_state, 2)
            
            if new_priority > old_priority:
                promotions += 1
            elif new_priority < old_priority:
                demotions += 1
        
        # Update state + calculate next_update_due
        interval_min = STATE_INTERVALS.get(new_state, 360)
        now = datetime.now(timezone.utc)
        supabase.table("stock_states").upsert({
            "ticker": ticker,
            "current_state": new_state,
            "promotion_reason": reason,
            "last_updated": now.isoformat(),
            "next_update_due": (now + timedelta(minutes=interval_min)).isoformat(),
            "consecutive_hot": (state_info.get("consecutive_hot", 0) + 1) if new_state == "HOT" else 0,
        }).execute()
    
    return promotions, demotions


def refresh_all_next_updates(supabase: Client):
    """
    After a daily full refresh, reset next_update_due for ALL tickers
    based on their current state. This ensures the cycle restarts cleanly.
    """
    for state, interval_min in STATE_INTERVALS.items():
        supabase.table("stock_states") \
            .update({
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "next_update_due": (datetime.now(timezone.utc) + timedelta(minutes=interval_min)).isoformat(),
            }) \
            .eq("current_state", state) \
            .execute()


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def run_prioritizer(force_all: bool = False) -> dict:
    """
    Main entry point. Called by n8n via Supabase Edge Function.
    
    Args:
        force_all: If True, returns ALL tickers (daily full refresh).
                   If False, returns only tickers due per Markov schedule.
    
    Returns:
        {
            "tickers": ["AAPL", "NVDA", ...],
            "count": 47,
            "states": {"HOT": 12, "WARM": 15, "COLD": 10, "FROZEN": 10},
            "force_all": False
        }
    """
    supabase = init_supabase()
    
    # Get tickers due for update
    due_tickers = get_tickers_due(supabase, force_all=force_all)
    
    if not due_tickers:
        return {
            "tickers": [],
            "count": 0,
            "states": {"HOT": 0, "WARM": 0, "COLD": 0, "FROZEN": 0},
            "force_all": force_all,
        }
    
    # Count by state
    state_counts = {"HOT": 0, "WARM": 0, "COLD": 0, "FROZEN": 0}
    ticker_list = []
    
    for t in due_tickers:
        ticker_list.append(t["ticker"])
        state = t.get("current_state", "COLD")
        state_counts[state] = state_counts.get(state, 0) + 1
    
    return {
        "tickers": ticker_list,
        "count": len(ticker_list),
        "states": state_counts,
        "force_all": force_all,
    }


def run_state_updater(tickers: list[str]) -> dict:
    """
    Step 4 of the pipeline. Called AFTER collector + scorer have run.
    Evaluates transition signals for freshly updated tickers and
    applies state changes.
    
    Args:
        tickers: List of tickers that were just collected + scored.
    
    Returns:
        {
            "transitions": {"AAPL": {"old": "WARM", "new": "HOT", "reason": "volume_spike_3x"}, ...},
            "promotions": 5,
            "demotions": 3,
        }
    """
    supabase = init_supabase()
    
    # Evaluate which tickers should change state
    transitions = evaluate_transitions(supabase, tickers)
    
    if not transitions:
        return {"transitions": {}, "promotions": 0, "demotions": 0}
    
    # Apply changes to database
    promotions, demotions = apply_transitions(supabase, transitions)
    
    return {
        "transitions": transitions,
        "promotions": promotions,
        "demotions": demotions,
    }


# ============================================================
# STANDALONE EXECUTION (for testing)
# ============================================================

if __name__ == "__main__":
    import sys
    
    force = "--force-all" in sys.argv
    
    print(f"{'='*60}")
    print(f"SeeSaw MFSES — Markov Prioritizer")
    print(f"Mode: {'DAILY FULL REFRESH' if force else 'MARKET HOURS (Markov)'}")
    print(f"{'='*60}")
    
    result = run_prioritizer(force_all=force)
    
    print(f"\nTickers due for update: {result['count']}")
    print(f"  HOT:    {result['states']['HOT']}")
    print(f"  WARM:   {result['states']['WARM']}")
    print(f"  COLD:   {result['states']['COLD']}")
    print(f"  FROZEN: {result['states']['FROZEN']}")
    
    if result["count"] > 0:
        print(f"\nFirst 10: {result['tickers'][:10]}")
    
    print(f"\nDone. Pass these tickers to collector.py →")
