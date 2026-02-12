"""
SeeSaw MFSES — Continuous Pipeline Scheduler
Runs the full data pipeline in a loop: prioritize → collect → score → update states → repeat.
"""

import os
import sys
import time
import traceback
from datetime import datetime, timezone

# Add scripts dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from markov import run_prioritizer, run_state_updater
from collector import run_collector
from scorer import run_scorer

# Minimum pause between cycles (seconds) to avoid hammering APIs if cycles are very fast
MIN_CYCLE_GAP = 10


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def run_cycle(cycle_num: int) -> dict:
    """Run one full pipeline cycle: prioritize → collect → score → update states."""

    log(f"===== CYCLE {cycle_num} START =====")
    cycle_start = time.time()

    # Step 1: Prioritize — get tickers due for update
    log("Step 1/4: Running prioritizer...")
    priority = run_prioritizer(force_all=False)
    tickers = priority.get("tickers", [])
    log(f"  Tickers due: {priority['count']} | States: {priority['states']}")

    if not tickers:
        log("  No tickers due. Waiting 60s before next check...")
        time.sleep(60)
        return {"cycle": cycle_num, "tickers": 0, "collected": 0, "scored": 0, "skipped": True}

    # Step 2: Collect — fetch data from Polygon
    log(f"Step 2/4: Collecting data for {len(tickers)} tickers...")
    collect_result = run_collector(tickers)
    log(f"  Collected: {collect_result['collected']} | Failed: {collect_result['failed']} | API calls: {collect_result['api_calls']}")

    if collect_result["errors"]:
        for err in collect_result["errors"][:5]:
            log(f"    ! {err}")

    # Step 3: Score — calculate MFSES v2 scores
    log(f"Step 3/4: Scoring {len(tickers)} tickers...")
    score_result = run_scorer(tickers)
    log(f"  Scored: {score_result['scored']} | Failed: {score_result['failed']}")
    log(f"  Avg Short: {score_result['avg_short']} | Mid: {score_result['avg_mid']} | Long: {score_result['avg_long']}")
    log(f"  Triple Crowns: {score_result['triple_crowns']}")

    # Step 4: Update Markov states based on fresh data
    log(f"Step 4/4: Updating Markov states...")
    state_result = run_state_updater(tickers)
    log(f"  Promotions: {state_result['promotions']} | Demotions: {state_result['demotions']}")

    elapsed = time.time() - cycle_start
    log(f"===== CYCLE {cycle_num} DONE in {elapsed:.1f}s =====\n")

    return {
        "cycle": cycle_num,
        "tickers": len(tickers),
        "collected": collect_result["collected"],
        "scored": score_result["scored"],
        "promotions": state_result["promotions"],
        "demotions": state_result["demotions"],
        "elapsed_s": round(elapsed, 1),
        "skipped": False,
    }


def main():
    log("SeeSaw MFSES Scheduler starting — continuous loop mode")
    log(f"Pipeline: prioritize -> collect -> score -> update states -> repeat")
    log(f"Min gap between cycles: {MIN_CYCLE_GAP}s")
    log("")

    cycle_num = 0

    while True:
        cycle_num += 1
        cycle_start = time.time()

        try:
            result = run_cycle(cycle_num)

            if result.get("skipped"):
                continue

        except KeyboardInterrupt:
            log("Scheduler stopped by user (Ctrl+C)")
            break
        except Exception as e:
            log(f"CYCLE {cycle_num} FAILED: {e}")
            traceback.print_exc()
            log("Waiting 120s before retry...")
            time.sleep(120)
            continue

        # Ensure minimum gap between cycles
        elapsed = time.time() - cycle_start
        if elapsed < MIN_CYCLE_GAP:
            time.sleep(MIN_CYCLE_GAP - elapsed)


if __name__ == "__main__":
    main()
