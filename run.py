"""
run.py — Full pipeline orchestrator. Runs all 5 agents in sequence.

Usage:
    python run.py                  # full run
    python run.py --skip-collect   # use existing data (skip agents 1+2)
    python run.py --no-email       # skip email delivery (agent 5)
"""

import sys
from agent1_discover import run as discover
from agent2_collect  import collect
from agent3_analyse  import run as analyse
from agent4_report   import run as build_report
from agent5_email    import run as send_email


def main():
    skip_collect = "--skip-collect" in sys.argv
    no_email     = "--no-email"     in sys.argv

    print("\n  CANDLE INTEL — FULL PIPELINE")
    print("  " + "="*40)

    # Agent 1 — discover niche + competitors
    config = discover()

    # Agent 2 — scrape product data
    if skip_collect:
        print("[Skipping data collection — using existing data]\n")
    else:
        collect(config["competitors"])

    # Agent 3 — AI analysis
    analyse()

    # Agent 4 — HTML report
    build_report()

    # Agent 5 — email delivery
    if no_email:
        print("\n[Skipping email — --no-email flag set]\n")
    else:
        send_email()

    print("  Pipeline complete.\n")


if __name__ == "__main__":
    main()
