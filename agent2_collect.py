"""
Agent 2 — Data Collection
Every Shopify store exposes /products.json — a free, public JSON endpoint.
No scraping, no HTML parsing. Just clean structured data.

Collects: product title, price, product type, whether it's new (created < 30 days ago).
Saves results to data/products_YYYY-MM-DD.json
"""

import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path


OUTPUT_DIR = Path("data")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


def fetch_shopify_products(base_url: str, max_pages: int = 3) -> list[dict]:
    """
    Hits /products.json with pagination.
    Returns a flat list of product dicts.
    """
    all_products = []
    page = 1

    while page <= max_pages:
        url = f"{base_url.rstrip('/')}/products.json?limit=250&page={page}"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode())
            products = body.get("products", [])
            if not products:
                break
            all_products.extend(products)
            page += 1
            time.sleep(0.5)          # be polite
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"    [INFO] {base_url} — /products.json not found (not Shopify?)")
            else:
                print(f"    [WARN] HTTP {e.code} from {base_url}")
            break
        except Exception as e:
            print(f"    [ERR] {base_url}: {e}")
            break

    return all_products


def parse_product(raw: dict, store_name: str, store_url: str) -> dict:
    """Extract only the fields we care about from a Shopify product."""
    # Lowest price across variants
    prices = []
    for v in raw.get("variants", []):
        try:
            prices.append(float(v["price"]))
        except (KeyError, ValueError, TypeError):
            pass

    min_price = min(prices) if prices else None
    max_price = max(prices) if prices else None

    # Is it newly listed? (published in last 30 days)
    created_str = raw.get("created_at", "")
    is_new = False
    if created_str:
        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            cutoff  = datetime.now(timezone.utc) - timedelta(days=30)
            is_new  = created > cutoff
        except ValueError:
            pass

    return {
        "store":        store_name,
        "store_url":    store_url,
        "title":        raw.get("title", ""),
        "product_type": raw.get("product_type", ""),
        "tags":         raw.get("tags", []),
        "min_price":    min_price,
        "max_price":    max_price,
        "variants":     len(raw.get("variants", [])),
        "is_new":       is_new,
        "created_at":   created_str,
        "handle":       raw.get("handle", ""),
        "url":          f"{store_url.rstrip('/')}/products/{raw.get('handle', '')}",
    }


def collect(competitors: list[dict]) -> list[dict]:
    """Run collection across all competitors. Returns all parsed products."""
    print(f"\n{'='*55}")
    print(f"  AGENT 2 — DATA COLLECTION")
    print(f"{'='*55}")

    all_products = []

    for comp in competitors:
        name = comp["name"]
        url  = comp["url"]
        print(f"\n  >> {name}")

        raw_products = fetch_shopify_products(url)
        if not raw_products:
            print(f"    No products found.")
            continue

        parsed = [parse_product(p, name, url) for p in raw_products]
        all_products.extend(parsed)

        new_count = sum(1 for p in parsed if p["is_new"])
        prices    = [p["min_price"] for p in parsed if p["min_price"] is not None]
        avg_price = round(sum(prices) / len(prices), 2) if prices else 0

        print(f"    Products  : {len(parsed)}")
        print(f"    New (30d) : {new_count}")
        print(f"    Avg price : ${avg_price}")

    # Save to file
    OUTPUT_DIR.mkdir(exist_ok=True)
    date_str  = datetime.now().strftime("%Y-%m-%d")
    out_path  = OUTPUT_DIR / f"products_{date_str}.json"

    with open(out_path, "w") as f:
        json.dump(all_products, f, indent=2)

    print(f"\n  {'='*51}")
    print(f"  Total products collected : {len(all_products)}")
    print(f"  Saved to                 : {out_path}")
    print(f"  {'='*51}\n")

    return all_products


if __name__ == "__main__":
    from agent1_discover import load_competitors
    config = load_competitors()
    collect(config["competitors"])
