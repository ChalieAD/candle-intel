"""
Agent 1 — Niche & Competitor Discovery
Loads the competitor config and prints a summary of what we're tracking.
In a future version this can call a search API (SerpAPI, Brave, etc.)
to discover competitors dynamically.
"""

import json
from pathlib import Path


def load_competitors(config_path: str = "competitors.json") -> dict:
    with open(config_path) as f:
        return json.load(f)


def run():
    data = load_competitors()
    niche = data["niche"]
    competitors = data["competitors"]

    print(f"\n{'='*55}")
    print(f"  AGENT 1 — NICHE & COMPETITOR DISCOVERY")
    print(f"{'='*55}")
    print(f"  Niche   : {niche}")
    print(f"  Tracking: {len(competitors)} competitors\n")
    for c in competitors:
        print(f"  - {c['name']:<25} {c['url']}")
    print(f"{'='*55}\n")

    return data


if __name__ == "__main__":
    run()
