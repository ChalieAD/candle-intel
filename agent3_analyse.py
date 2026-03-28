"""
Agent 3 — AI Analysis (4-step sub-agent chain)

Chain:
  Step 0 — Sanitise scraped data (prompt injection guard)
  Step 1 — Analyst:    factual observations from today + 7-day history
  Step 2 — Strategist: implications for the client from analyst output
  Step 3 — Advisor:    3 prioritised suggestions from strategist output
  Step 4 — Writer:     human daily briefing from all three outputs

Returns a dict with all four outputs + metadata.
Saves metrics_YYYY-MM-DD.json and report_YYYY-MM-DD.md for agent4.
Writes the full result dict to Supabase agent_outputs.
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Supabase helpers ──────────────────────────────────────────────────────────

def _sb_headers() -> dict:
    key = os.environ["SUPABASE_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def fetch_historical(days: int = 30) -> list[dict]:
    """
    Return deduplicated daily summaries from agent_outputs for the last `days` days,
    newest first. One entry per run_date — keeps the latest created_at per day.
    Returns [] on any error so the chain can proceed without history.
    """
    url   = os.environ["SUPABASE_URL"]
    since = (date.today() - timedelta(days=days)).isoformat()
    try:
        resp = requests.get(
            f"{url}/rest/v1/agent_outputs",
            headers=_sb_headers(),
            params={
                "agent_name": "eq.candle-intel",
                "run_date":   f"gte.{since}",
                "order":      "run_date.desc,created_at.desc",
                "limit":      "200",
            },
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        print(f"  [WARN] Supabase fetch failed: {exc}")
        return []

    # Deduplicate: keep first occurrence of each run_date (= latest created_at)
    seen   = set()
    unique = []
    for row in rows:
        rd = row.get("run_date")
        if rd not in seen:
            seen.add(rd)
            unique.append({"run_date": rd, "summary": row.get("summary", {})})
    return unique


def save_to_supabase(result: dict) -> None:
    """Insert the full result dict into agent_outputs."""
    url = os.environ["SUPABASE_URL"]
    payload = {
        "agent_name": "candle-intel",
        "run_date":   result["run_date"],
        "summary":    result,
    }
    try:
        resp = requests.post(
            f"{url}/rest/v1/agent_outputs",
            headers=_sb_headers(),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        print("  Saved to Supabase agent_outputs.")
    except Exception as exc:
        print(f"  [WARN] Supabase write failed: {exc}")


# ── Step 0 — Sanitise ─────────────────────────────────────────────────────────

# Known-safe internal tag prefixes used by Shopify apps — never flag these.
_TAG_ALLOWLIST_PREFIXES = (
    "algolia-",
    "shopify-",
    "seo-",
    "yotpo-",
)

# "ignore" and "disregard" are only injections when they stand alone —
# not when hyphen-joined in a compound tag (e.g. "algolia-ignore").
# Uses character-class boundaries instead of \b so hyphens are excluded.
# "system:" / "assistant:" handled separately since they end in a non-word char.
_INJECTION_PATTERN = re.compile(
    r"(?<![a-zA-Z0-9-])(ignore|disregard)(?![a-zA-Z0-9-])"   # standalone only
    r"|(?<!\w)(pretend|you\s+are)(?!\w)"                       # word-bounded
    r"|(system|assistant)\s*:",                                 # colon-terminated roles
    re.IGNORECASE,
)


def _is_allowlisted_tag(value: str) -> bool:
    low = value.lower()
    return any(low.startswith(prefix) for prefix in _TAG_ALLOWLIST_PREFIXES)


def _sanitise_value(value: str, field_path: str, warnings: list) -> str:
    if _is_allowlisted_tag(value):
        return value
    if _INJECTION_PATTERN.search(value):
        warnings.append(f"Sanitised field '{field_path}': {value!r}")
        return _INJECTION_PATTERN.sub("[removed]", value)
    return value


def sanitise_products(products: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Strip prompt-injection text from all scraped string fields.
    Returns (cleaned_products, warnings).
    """
    warnings: list[str] = []
    string_fields = ("title", "product_type", "store")

    cleaned = []
    for i, p in enumerate(products):
        cp = dict(p)
        for field in string_fields:
            if isinstance(cp.get(field), str):
                cp[field] = _sanitise_value(cp[field], f"[{i}].{field}", warnings)
        if isinstance(cp.get("tags"), list):
            cp["tags"] = [
                _sanitise_value(t, f"[{i}].tags[{j}]", warnings) if isinstance(t, str) else t
                for j, t in enumerate(cp["tags"])
            ]
        cleaned.append(cp)

    return cleaned, warnings


# ── Data loader ───────────────────────────────────────────────────────────────

def load_latest(data_dir: str = "data") -> list[dict]:
    files = sorted(Path(data_dir).glob("products_*.json"), reverse=True)
    if not files:
        raise FileNotFoundError(f"No product files found in '{data_dir}/'")
    path = files[0]
    print(f"  Loading: {path}")
    with open(path) as f:
        return json.load(f)


# ── Metrics (unchanged from original — feeds agent4 via files) ────────────────

from collections import Counter

def compute_metrics(products: list[dict]) -> dict:
    stores = {}
    for p in products:
        name = p["store"]
        if name not in stores:
            stores[name] = {
                "url": p["store_url"], "products": [], "prices": [],
                "new_drops": [], "types": [], "tags": [],
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

    store_summary = {}
    all_prices    = []
    for name, s in stores.items():
        prices = s["prices"]
        all_prices.extend(prices)
        top_types = [t for t, _ in Counter(s["types"]).most_common(5)] if s["types"] else []
        top_tags  = [t for t, _ in Counter(s["tags"]).most_common(8)]  if s["tags"]  else []
        store_summary[name] = {
            "total_products":    len(s["products"]),
            "new_last_30d":      len(s["new_drops"]),
            "new_titles":        s["new_drops"][:10],
            "avg_price":         round(sum(prices) / len(prices), 2) if prices else None,
            "min_price":         round(min(prices), 2) if prices else None,
            "max_price":         round(max(prices), 2) if prices else None,
            "top_product_types": top_types,
            "top_tags":          top_tags,
            "url":               s["url"],
        }

    all_types = [p["product_type"] for p in products if p["product_type"]]
    all_tags  = [t for p in products if isinstance(p["tags"], list) for t in p["tags"]]

    return {
        "date":              date.today().strftime("%Y-%m-%d"),
        "total_products":    len(products),
        "total_stores":      len(store_summary),
        "price_tiers": {
            "budget_under_25":   sum(1 for p in all_prices if p < 25),
            "mid_25_to_50":      sum(1 for p in all_prices if 25 <= p < 50),
            "premium_50_to_100": sum(1 for p in all_prices if 50 <= p < 100),
            "luxury_100_plus":   sum(1 for p in all_prices if p >= 100),
        },
        "top_product_types": [t for t, _ in Counter(all_types).most_common(10)],
        "top_tags":          [t for t, _ in Counter(all_tags).most_common(15)],
        "stores":            store_summary,
    }


# ── Groq caller ───────────────────────────────────────────────────────────────

def _call_groq(client: Groq, system: str, user: str, step_name: str) -> str:
    print(f"  [{step_name}] Calling Groq ({GROQ_MODEL})...")
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return resp.choices[0].message.content


# ── Step 1 — Analyst ──────────────────────────────────────────────────────────

ANALYST_SYSTEM = """You are a market data analyst. Your only job is to report what the data shows.
You do not interpret. You do not advise. You do not speculate.

You have access to:
- Today's scraped product data for all tracked stores including the client's own store
- Historical snapshots from the past 7 days and 30 days stored in Supabase

Rules:
- Every observation MUST reference a specific brand name and a specific number
- If data is missing or unchanged, say so explicitly — do not fill gaps with assumptions
- You are FORBIDDEN from using these phrases: "in today's competitive landscape", \
"consider", "it appears", "seems to", "may want to", "could potentially"
- Output must include a DATA QUALITY REPORT section listing any stores with missing, \
stale, or suspicious data before the main observations

Output format:
DATA QUALITY REPORT:
[list any data issues]

FACTUAL OBSERVATIONS:
[numbered list of specific, data-backed observations with brand names and numbers]"""


def run_analyst(client: Groq, metrics: dict, history: list[dict]) -> str:
    history_block = ""
    if history:
        lines = []
        for h in history[:7]:
            lines.append(f"run_date={h['run_date']}: {json.dumps(h['summary'])}")
        history_block = "\n\nHISTORICAL SNAPSHOTS (last 7 days, newest first):\n" + "\n".join(lines)

    user = (
        f"TODAY'S METRICS:\n```json\n{json.dumps(metrics, indent=2)}\n```"
        f"{history_block}"
    )
    return _call_groq(client, ANALYST_SYSTEM, user, "Analyst")


# ── Step 2 — Strategist ───────────────────────────────────────────────────────

STRATEGIST_SYSTEM = """You are a business strategist working exclusively for the client brand.
You receive factual observations from a data analyst. Your job is to identify \
what these facts mean for the client specifically.

Rules:
- You can only draw implications from observations explicitly stated in the input
- Every implication must name which observation it comes from
- You do not make recommendations — only implications
- You are FORBIDDEN from generic implications that could apply to any brand
- If an observation has no clear implication for the client, say "no direct implication identified"

Output format:
IMPLICATIONS:
[numbered list, each one referencing a specific observation and explaining what it means for the client]"""


def run_strategist(client: Groq, analyst_output: str) -> str:
    return _call_groq(client, STRATEGIST_SYSTEM, analyst_output, "Strategist")


# ── Step 3 — Advisor ──────────────────────────────────────────────────────────

ADVISOR_SYSTEM = """You are a trusted advisor to a small ecommerce brand owner. You receive a list of \
implications about their market. Your job is to surface what deserves their attention today.

Rules:
- Output exactly 3 suggestions
- Each suggestion MUST cite the specific data observation that supports it
- CRITICAL: Never reference observation numbers like 'Observation 6' or \
'Observations 8 and 9' in your output. The client does not see the \
observation list. Always describe the actual finding in plain words instead.
- Suggestion 3 can be "what to monitor this week" if there are fewer than 3 actionable insights
- Express a confidence level for each: HIGH / MEDIUM / LOW with one sentence explaining why
- You are FORBIDDEN from these phrases: "launch new products", "optimize your listings", \
"engage with customers", "leverage social media", "consider diversifying", \
"in today's competitive landscape", "stay competitive"
- Tone: trusted analyst, not consultant. Say "today's data suggests" not "you must" or "you should"

Output format:
SUGGESTION 1 [CONFIDENCE: HIGH/MEDIUM/LOW]
Data behind this: [specific observation]
What it suggests: [one specific, actionable direction]
Why this confidence level: [one sentence]

SUGGESTION 2 [CONFIDENCE: HIGH/MEDIUM/LOW]
Data behind this: [specific observation]
What it suggests: [one specific, actionable direction]
Why this confidence level: [one sentence]

SUGGESTION 3 — MONITOR [CONFIDENCE: HIGH/MEDIUM/LOW]
Data behind this: [specific observation]
What it suggests: [one specific, actionable direction]
Why this confidence level: [one sentence]"""


def run_advisor(client: Groq, strategist_output: str) -> str:
    return _call_groq(client, ADVISOR_SYSTEM, strategist_output, "Advisor")


# ── Step 4 — Writer ───────────────────────────────────────────────────────────

WRITER_SYSTEM = """You are writing a daily briefing for a small candle brand owner. You receive structured \
analysis from three sources. Your job is to turn this into a clear, human briefing.

Rules:
- Write like a smart analyst who respects the reader's time
- Never pad. If there are only 2 strong things to say, say 2 things well
- Preserve all confidence levels and data references from the Advisor
- Do not upgrade LOW confidence suggestions to sound more certain
- Do not add advice that wasn't in the Advisor output
- Tone: direct, warm, specific. Like a trusted colleague, not a report

Plain language rules:
- Write like a smart friend explaining this to a busy small business owner
- If you wouldn't say it out loud to someone's face, don't write it
- Never use these words or phrases: benchmark, anomaly, positioning, \
segment, active launchers, strategic hold, catalogue depth, \
mid-range dominates, leverage, optimise
- Replace jargon with plain equivalents:
  'pricing benchmark' → 'how your prices compare'
  'anomaly' → 'something looks off'
  'mid-range segment' → 'candles priced between $25–$50'
  'active launchers' → 'brands dropping new products'
  'catalogue' → 'product range'
- Numbers always have context: not '50.6%' but '50.6% of the 500 products we track'
- If something is uncertain, say so plainly: 'we're not sure yet' not 'data is insufficient'
- Maximum reading age: smart 16 year old. Minimum: don't be patronising.
- Never start a suggestion with 'Today's data suggests' — \
lead with the specific finding instead. For example: \
'Keap's pricing shows a $0 minimum — leave them out of \
your pricing comparisons this week' not \
'Today's data suggests investigating Keap's pricing'
- Chain fidelity is non-negotiable: every suggestion in YOUR 3 FOCUS \
AREAS must preserve the Advisor's exact data citation and specific \
direction. You may reword for plain language but you cannot soften, \
generalise, or replace a specific suggestion with a vague one. \
If the Advisor says 'Keap's $0 price looks broken — don't use it \
for comparisons', the Writer must say exactly that in plain words. \
It must NOT become 'review your pricing strategy' or \
'research customer demand'. Specific in, specific out.

Output format:
WHAT HAPPENED TODAY
[2-3 sentences summarising the Analyst's key observations in plain English]

WHAT IT MEANS FOR YOU
[The implications in plain English, keeping it specific to the client]

YOUR 3 FOCUS AREAS TODAY
[The 3 suggestions rewritten in plain English, confidence levels preserved]

DATA NOTES
[Any data quality issues flagged by the Analyst, written plainly]"""


def run_writer(
    analyst_output: str,
    strategist_output: str,
    advisor_output: str,
) -> str:
    print("  [Writer] Calling Claude Haiku (claude-haiku-4-5-20251001)...")
    user = (
        f"ANALYST OUTPUT:\n{analyst_output}\n\n"
        f"STRATEGIST OUTPUT:\n{strategist_output}\n\n"
        f"ADVISOR OUTPUT:\n{advisor_output}"
    )
    ac = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = ac.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=WRITER_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


# ── Save files for agent4 ─────────────────────────────────────────────────────

def save_files(metrics: dict, writer_output: str, out_dir: str = "reports") -> None:
    Path(out_dir).mkdir(exist_ok=True)
    date_str = metrics["date"]

    # metrics JSON — agent4 reads this for all data pages
    json_path = Path(out_dir) / f"metrics_{date_str}.json"
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"  Saved: {json_path}")

    # writer output as report markdown — agent4 reads this for AI text sections
    md_path = Path(out_dir) / f"report_{date_str}.md"
    header  = (
        f"# Candle Intel Daily Briefing\n"
        f"**Date:** {date_str}  |  "
        f"**Stores:** {metrics['total_stores']}  |  "
        f"**Products:** {metrics['total_products']}\n\n---\n\n"
    )
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(header + writer_output)
    print(f"  Saved: {md_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def run() -> dict:
    print(f"\n{'='*60}")
    print("  AGENT 3 -- AI ANALYSIS (4-step chain)")
    print(f"{'='*60}\n")

    # Load raw products
    products = load_latest()
    print(f"  {len(products)} products loaded\n")

    # Step 0 — Sanitise
    print("  Step 0: Sanitising scraped data...")
    products, dq_warnings = sanitise_products(products)
    if dq_warnings:
        print(f"  [WARN] {len(dq_warnings)} field(s) sanitised:")
        for w in dq_warnings:
            print(f"    {w}")
    else:
        print("  No injection patterns detected.")

    # Compute metrics (for agent4 file output + analyst context)
    print("\n  Computing metrics...")
    metrics = compute_metrics(products)

    # Fetch Supabase history
    print("\n  Fetching historical data from Supabase...")
    history = fetch_historical(days=30)
    print(f"  {len(history)} historical snapshot(s) found (deduped by day).")

    # Groq client
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY not set. Add it to your .env file."
        )
    groq_client = Groq(api_key=api_key)

    # Step 1 — Analyst
    print()
    analyst_output = run_analyst(groq_client, metrics, history)

    # Step 2 — Strategist (analyst output only)
    strategist_output = run_strategist(groq_client, analyst_output)

    # Step 3 — Advisor (strategist output only)
    advisor_output = run_advisor(groq_client, strategist_output)

    # Step 4 — Writer (all three outputs)
    writer_output = run_writer(analyst_output, strategist_output, advisor_output)

    # Assemble result
    result = {
        "run_date":            date.today().isoformat(),
        "analyst_output":      analyst_output,
        "strategist_output":   strategist_output,
        "advisor_output":      advisor_output,
        "writer_output":       writer_output,
        "data_quality_warnings": dq_warnings,
    }

    # Save files for agent4
    print()
    save_files(metrics, writer_output)

    # Save full agent3 output dict for agent4 structured parsing
    a3_path = Path("reports") / f"agent3_{result['run_date']}.json"
    with open(a3_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"  Saved: {a3_path}")

    # Save to Supabase
    save_to_supabase(result)

    # Print the briefing
    width = 60
    print("\n" + "=" * width)
    print("  DAILY BRIEFING")
    print("=" * width)
    print(writer_output)
    print("=" * width + "\n")

    return result


if __name__ == "__main__":
    run()
