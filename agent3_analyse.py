"""
Agent 3 — AI Analysis
Loads collected product data, computes structured metrics,
sends them to Claude, and prints a clean insight report.
"""

import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from groq import Groq
from dotenv import load_dotenv

load_dotenv()


# ── Load data ────────────────────────────────────────────────────────────────

def load_latest(data_dir: str = "data") -> list[dict]:
    files = sorted(Path(data_dir).glob("products_*.json"), reverse=True)
    if not files:
        raise FileNotFoundError(f"No product files found in '{data_dir}/'")
    path = files[0]
    print(f"  Loading: {path}")
    with open(path) as f:
        return json.load(f)


# ── Compute metrics ───────────────────────────────────────────────────────────

def compute_metrics(products: list[dict]) -> dict:
    stores = {}

    for p in products:
        name = p["store"]
        if name not in stores:
            stores[name] = {
                "url":       p["store_url"],
                "products":  [],
                "prices":    [],
                "new_drops": [],
                "types":     [],
                "tags":      [],
            }
        s = stores[name]
        s["products"].append(p["title"])
        if p["min_price"] is not None:
            s["prices"].append(p["min_price"])
        if p["is_new"]:
            s["new_drops"].append(p["title"])
        if p["product_type"]:
            s["types"].append(p["product_type"])
        if isinstance(p["tags"], list):
            s["tags"].extend(p["tags"])

    # Summarise per store
    store_summary = {}
    all_prices = []
    for name, s in stores.items():
        prices = s["prices"]
        all_prices.extend(prices)
        top_types = [t for t, _ in Counter(s["types"]).most_common(5)] if s["types"] else []
        top_tags  = [t for t, _ in Counter(s["tags"]).most_common(8)]  if s["tags"]  else []

        store_summary[name] = {
            "total_products": len(s["products"]),
            "new_last_30d":   len(s["new_drops"]),
            "new_titles":     s["new_drops"][:10],
            "avg_price":      round(sum(prices) / len(prices), 2) if prices else None,
            "min_price":      round(min(prices), 2) if prices else None,
            "max_price":      round(max(prices), 2) if prices else None,
            "top_product_types": top_types,
            "top_tags":       top_tags,
            "url":            s["url"],
        }

    # Price tier breakdown across all stores
    budget   = sum(1 for p in all_prices if p < 25)
    mid      = sum(1 for p in all_prices if 25 <= p < 50)
    premium  = sum(1 for p in all_prices if 50 <= p < 100)
    luxury   = sum(1 for p in all_prices if p >= 100)

    # Most common product types overall
    all_types = []
    all_tags  = []
    for p in products:
        if p["product_type"]:
            all_types.append(p["product_type"])
        if isinstance(p["tags"], list):
            all_tags.extend(p["tags"])

    top_types_overall = [t for t, _ in Counter(all_types).most_common(10)]
    top_tags_overall  = [t for t, _ in Counter(all_tags).most_common(15)]

    return {
        "date":            datetime.now().strftime("%Y-%m-%d"),
        "total_products":  len(products),
        "total_stores":    len(store_summary),
        "price_tiers": {
            "budget_under_25":   budget,
            "mid_25_to_50":      mid,
            "premium_50_to_100": premium,
            "luxury_100_plus":   luxury,
        },
        "top_product_types": top_types_overall,
        "top_tags":          top_tags_overall,
        "stores":            store_summary,
    }


# ── Claude analysis ───────────────────────────────────────────────────────────

SYSTEM = """You are a sharp e-commerce market analyst specialising in the candle and home fragrance industry.
You receive structured competitor data scraped from real Shopify stores.
Write a concise, punchy intelligence report for a small candle business owner.
Be specific with numbers. Use plain language. No fluff."""

PROMPT_TEMPLATE = """Here is today's competitor data for the handmade candle niche:

```json
{metrics}
```

Write a market intelligence report with these exact sections:

## 1. Market Snapshot
One short paragraph: overall picture, how many products tracked, date.

## 2. Pricing Landscape
Table showing each store's avg / min / max price and total products.
Then 2-3 sentences on what the pricing tells us.

## 3. New Drop Activity
Which stores launched new products in the last 30 days?
List the actual new product titles. Who is most active?

## 4. Product & Category Trends
What types of products and themes are dominating?
What tags and keywords keep appearing? What does this signal?

## 5. Store-by-Store Breakdown
One bullet per store: their positioning, price point, activity level.

## 6. Actionable Insights for a Candle Business Owner
Numbered list of exactly 5 specific, practical insights they can act on this week.
Each insight should reference real data from the report."""


def analyse(metrics: dict, api_key: str) -> str:
    client = Groq(api_key=api_key)

    prompt = PROMPT_TEMPLATE.format(
        metrics=json.dumps(metrics, indent=2)
    )

    print("  Sending to Groq (llama-3.3-70b-versatile)...")
    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": prompt},
        ],
    )
    return message.choices[0].message.content


# ── Report output ─────────────────────────────────────────────────────────────

def print_report(report: str, metrics: dict):
    width = 60
    print("\n" + "=" * width)
    print("  CANDLE MARKET INTELLIGENCE REPORT")
    print(f"  {metrics['date']}  |  {metrics['total_stores']} stores  |  {metrics['total_products']} products")
    print("=" * width)
    print()
    print(report)
    print()
    print("=" * width)


def save_report(report: str, metrics: dict, out_dir: str = "reports"):
    Path(out_dir).mkdir(exist_ok=True)
    date_str = metrics["date"]

    # Save markdown
    md_path = Path(out_dir) / f"report_{date_str}.md"
    header  = f"# Candle Market Intelligence Report\n**Date:** {date_str}  |  **Stores:** {metrics['total_stores']}  |  **Products:** {metrics['total_products']}\n\n---\n\n"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(header + report)
    print(f"  Saved: {md_path}")

    # Save metrics JSON alongside
    json_path = Path(out_dir) / f"metrics_{date_str}.json"
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"  Saved: {json_path}")

    return str(md_path)


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*60}")
    print("  AGENT 3 -- AI ANALYSIS")
    print(f"{'='*60}\n")

    # Load
    products = load_latest()
    print(f"  {len(products)} products loaded\n")

    # Metrics
    print("  Computing metrics...")
    metrics = compute_metrics(products)

    # Claude
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY not set.\n"
            "Add it to your .env file: GROQ_API_KEY=your_key_here\n"
            "Get a free key at: console.groq.com"
        )

    report = analyse(metrics, api_key)

    # Output
    print_report(report, metrics)
    save_report(report, metrics)


if __name__ == "__main__":
    run()
