"""
Agent 4 — PDF Report Generator (Playwright / HTML)
Builds one large HTML string, renders with headless Chromium to produce an A4 PDF.
"""

import html as htmllib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# ── Loaders ───────────────────────────────────────────────────────────────────

def load_latest(reports_dir="reports"):
    p = Path(reports_dir)
    json_files = sorted(p.glob("metrics_*.json"), reverse=True)
    md_files   = sorted(p.glob("report_*.md"),    reverse=True)
    a3_files   = sorted(p.glob("agent3_*.json"),  reverse=True)
    if not json_files:
        raise FileNotFoundError("No metrics_*.json found in reports/")
    with open(json_files[0]) as f:
        metrics = json.load(f)
    md = ""
    if md_files:
        with open(md_files[0], encoding="utf-8") as f:
            md = f.read()
    agent3 = None
    if a3_files:
        with open(a3_files[0], encoding="utf-8") as f:
            agent3 = json.load(f)
    return metrics, md, agent3

# ── Helpers ───────────────────────────────────────────────────────────────────

def esc(s):
    return htmllib.escape(str(s))

def momentum_score(s):
    new_drops   = s.get("new_last_30d", 0)
    total       = s.get("total_products", 0)
    mn          = s.get("min_price") or 0
    mx          = s.get("max_price") or 0
    price_range = max(mx - mn, 0)
    raw = (new_drops * 0.5) + (total / 50) + (price_range / 100)
    return min(10, round(raw))

def score_color(score):
    if score >= 8: return "#16a34a"
    if score >= 5: return "#d97706"
    return "#94a3b8"

def segment(avg_price):
    if avg_price is None: return "—"
    if avg_price < 25:    return "Budget"
    if avg_price < 50:    return "Mid-Range"
    if avg_price < 100:   return "Premium"
    return "Luxury"

SEGMENT_STYLE = {
    "Mid-Range": "background:#dbeafe;color:#1e40af;",
    "Premium":   "background:#fef3c7;color:#92400e;",
    "Luxury":    "background:#f3e8ff;color:#7e22ce;",
    "Budget":    "background:#dcfce7;color:#166534;",
}

def strip_md(text):
    return re.sub(r"\*+", "", text).strip()

def parse_snapshot(md):
    m = re.search(r"##\s*1\.\s*Market Snapshot\s*\n(.+?)(?=\n##|\Z)", md, re.DOTALL)
    return m.group(1).strip() if m else "No AI snapshot available for this run."

def parse_actions(md, count=3):
    m = re.search(r"##\s*6\.\s*Actionable Insights[^\n]*\n(.+?)(?=\n##|\Z)", md, re.DOTALL)
    if not m:
        return [("No actions available.", "") for _ in range(count)]
    block = m.group(1).strip()
    items = re.findall(r"^\d+\.\s+(.+)", block, re.MULTILINE)
    result = []
    for item in items[:count]:
        clean = strip_md(item.strip())
        if ":" in clean:
            title, _, body = clean.partition(":")
            result.append((title.strip(), body.strip()))
        elif "." in clean:
            title, _, body = clean.partition(".")
            result.append((title.strip(), body.strip()))
        else:
            words = clean.split()
            title = " ".join(words[:6])
            body  = " ".join(words[6:])
            result.append((title, body))
    while len(result) < count:
        result.append(("No further actions available.", ""))
    return result

def parse_writer_page1(agent3):
    """
    Extract WHAT HAPPENED TODAY and WHAT IT MEANS FOR YOU from writer_output.
    Returns a dict with keys 'happened' and 'means', or None if not parseable.
    """
    text = (agent3 or {}).get("writer_output", "")
    if not text:
        return None

    # Headers may appear bare or with markdown ## prefix
    _sec = r"(?:#{1,3}\s*)?"
    happened_m = re.search(
        rf"{_sec}WHAT HAPPENED TODAY\s*\n(.+?)(?=\n{_sec}WHAT IT MEANS FOR YOU|\n{_sec}YOUR 3|\n{_sec}DATA NOTES|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    means_m = re.search(
        rf"{_sec}WHAT IT MEANS FOR YOU\s*\n(.+?)(?=\n{_sec}YOUR 3|\n{_sec}DATA NOTES|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if not happened_m and not means_m:
        return None
    return {
        "happened": happened_m.group(1).strip() if happened_m else "",
        "means":    means_m.group(1).strip()    if means_m    else "",
    }


def parse_advisor_suggestions(agent3):
    """
    Parse SUGGESTION blocks from advisor_output.
    Returns list of dicts: {title, body, data_citation, confidence, is_monitor}
    or None if not parseable.
    """
    text = (agent3 or {}).get("advisor_output", "")
    if not text:
        return None

    blocks = re.split(r"(?=SUGGESTION\s+\d)", text.strip(), flags=re.IGNORECASE)
    results = []
    for block in blocks:
        block = block.strip()
        if not re.match(r"SUGGESTION\s+\d", block, re.IGNORECASE):
            continue

        conf_m     = re.search(r"\[CONFIDENCE:\s*(HIGH|MEDIUM|LOW)\]", block, re.IGNORECASE)
        confidence = conf_m.group(1).upper() if conf_m else "MEDIUM"
        is_monitor = bool(re.search(r"SUGGESTION\s+\d+\s*[—\-]\s*MONITOR", block, re.IGNORECASE))

        data_m  = re.search(r"Data behind this:\s*(.+?)(?=\nWhat it suggests:|\Z)", block, re.IGNORECASE | re.DOTALL)
        body_m  = re.search(r"What it suggests:\s*(.+?)(?=\nWhy this confidence|\Z)",  block, re.IGNORECASE | re.DOTALL)

        data_citation = data_m.group(1).strip() if data_m else ""
        body          = body_m.group(1).strip() if body_m else block.split("\n", 1)[-1].strip()

        # Title: first sentence of body (up to first full stop or 80 chars)
        title = re.split(r"(?<=\w)\.(?=\s|$)", body)[0].strip()
        if len(title) > 90:
            title = title[:87].rstrip() + "…"

        results.append({
            "confidence":   confidence,
            "is_monitor":   is_monitor,
            "data_citation": data_citation,
            "body":         body,
            "title":        title,
        })

    return results if results else None


def category_counts(metrics):
    counter = Counter()
    for s in metrics["stores"].values():
        for pt in s.get("top_product_types", []):
            counter[pt] += 1
    return counter.most_common(12)

# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 12px;
  line-height: 1.6;
  background: white;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}
.page {
  width: 210mm;
  height: 297mm;
  page-break-after: always;
  overflow: hidden;
  position: relative;
  display: flex;
  flex-direction: column;
}
.page:last-child { page-break-after: avoid; }
.top-bar { height: 6px; background: #0f172a; flex-shrink: 0; }
.content {
  flex: 1;
  padding: 32px 36px 48px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.page-footer {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 36px;
  border-top: 1px solid #e2e8f0;
  padding: 0 36px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 9px;
  color: #94a3b8;
  background: white;
}
.sh {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #0f172a;
  padding-bottom: 7px;
  border-bottom: 2px solid #f97316;
  margin-bottom: 14px;
  margin-top: 24px;
}
.sh.first { margin-top: 0; }
table { width: 100%; border-collapse: collapse; font-size: 10px; }
thead tr { background: #0f172a; }
thead th {
  padding: 8px 10px;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
  text-align: left;
  color: white;
}
tbody td { padding: 8px 10px; border-bottom: 1px solid #e2e8f0; color: #334155; }
tbody tr:nth-child(even) td { background: #f8fafc; }
.pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 9px;
  font-weight: 700;
}
.cat-pill {
  display: inline-block;
  padding: 2px 5px;
  border-radius: 3px;
  background: #f1f5f9;
  color: #475569;
  font-size: 9px;
  margin: 1px 2px 1px 0;
}
"""

# ── Shared components ─────────────────────────────────────────────────────────

def footer_html(date_fmt, page_num):
    return (
        f'<div class="page-footer">'
        f'<span>Candle Intel · Daily Intelligence Report</span>'
        f'<span>{esc(date_fmt)} · Page {page_num}</span>'
        f'</div>'
    )

# ── Page 1 — Executive Summary ────────────────────────────────────────────────

def page1_html(metrics, md, agent3=None):
    date_str   = metrics["date"]
    date_fmt   = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    stores     = metrics["stores"]
    total_new  = sum(s["new_last_30d"] for s in stores.values())
    avg_prices = [s["avg_price"] for s in stores.values() if s.get("avg_price")]
    market_avg = f"${round(sum(avg_prices)/len(avg_prices), 2)}" if avg_prices else "—"
    total_p    = metrics["total_products"]
    total_s    = metrics["total_stores"]
    writer_p1  = parse_writer_page1(agent3)

    most_active  = max(stores.items(), key=lambda x: x[1].get("new_last_30d", 0))
    all_min_vals = [s["min_price"] for s in stores.values() if s.get("min_price") is not None]
    all_max_vals = [s["max_price"] for s in stores.values() if s.get("max_price") is not None]
    all_min      = min(all_min_vals) if all_min_vals else 0
    all_max      = max(all_max_vals) if all_max_vals else 0

    kpi_items = [
        (str(total_p),   "Total Products Tracked"),
        (str(total_s),   "Competitors Monitored"),
        (str(total_new), "New Drops (Last 30 Days)"),
        (market_avg,     "Market Average Price"),
    ]
    kpi_html = ""
    for val, label in kpi_items:
        kpi_html += (
            f'<div style="border:1px solid #e2e8f0;border-top:3px solid #f97316;'
            f'border-radius:6px;padding:16px 18px;">'
            f'<div style="font-size:32px;font-weight:700;color:#0f172a;margin-bottom:4px;">{esc(val)}</div>'
            f'<div style="font-size:9px;text-transform:uppercase;color:#64748b;letter-spacing:0.1em;">{esc(label)}</div>'
            f'</div>'
        )

    overview_rows = [
        ("Most Active Brand",          f"{esc(most_active[0])} — {most_active[1].get('new_last_30d', 0)} new drops"),
        ("Market Price Range",         f"${all_min} – ${all_max}"),
        ("Total New Drops This Month", str(total_new)),
    ]
    overview_html = ""
    for label, value in overview_rows:
        overview_html += (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:10px 0;border-bottom:1px solid #f1f5f9;">'
            f'<span style="color:#64748b;font-size:10px;">{label}</span>'
            f'<span style="color:#0f172a;font-size:10px;font-weight:700;">{value}</span>'
            f'</div>'
        )

    if writer_p1:
        insight_html = (
            f'<div style="background:#f8fafc;border-left:3px solid #f97316;border-radius:0 6px 6px 0;'
            f'padding:14px 16px;font-size:11px;color:#334155;line-height:1.7;margin-bottom:12px;">'
            f'{esc(writer_p1["happened"])}'
            f'</div>'
            f'<div class="sh">What It Means For You</div>'
            f'<div style="background:#f8fafc;border-left:3px solid #0f172a;border-radius:0 6px 6px 0;'
            f'padding:14px 16px;font-size:11px;color:#334155;line-height:1.7;">'
            f'{esc(writer_p1["means"])}'
            f'</div>'
        )
    else:
        insight_html = (
            f'<div style="background:#f8fafc;border-left:3px solid #f97316;border-radius:0 6px 6px 0;'
            f'padding:14px 16px;font-size:11px;color:#334155;line-height:1.7;">'
            f'{esc(parse_snapshot(md))}'
            f'</div>'
        )

    return (
        f'<div class="page">'
        # Banner
        f'<div style="background:#0f172a;padding:28px 36px;display:flex;'
        f'justify-content:space-between;align-items:center;flex-shrink:0;">'
        f'<div>'
        f'<div style="font-size:22px;font-weight:700;color:white;line-height:1;">CANDLE INTEL</div>'
        f'<div style="font-size:10px;color:#94a3b8;margin-top:5px;">Daily Intelligence Report</div>'
        f'</div>'
        f'<div style="font-size:11px;color:#94a3b8;">{esc(date_fmt)}</div>'
        f'</div>'
        # Orange accent line
        f'<div style="height:3px;background:#f97316;flex-shrink:0;"></div>'
        # Content
        f'<div class="content" style="padding-top:28px;">'
        f'<div class="sh first">Today\'s Metrics</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px;">'
        f'{kpi_html}'
        f'</div>'
        f'<div class="sh">What Happened Today</div>'
        f'{insight_html}'
        f'<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;">'
        f'<div class="sh">Market Overview</div>'
        f'{overview_html}'
        f'</div>'
        f'</div>'
        f'{footer_html(date_fmt, 1)}'
        f'</div>'
    )

# ── Page 2 — Market Momentum ──────────────────────────────────────────────────

def page2_html(metrics):
    date_str = metrics["date"]
    date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    stores   = metrics["stores"]

    scores = {}
    rows_html = ""
    for name, s in stores.items():
        mn  = s.get("min_price") or 0
        mx  = s.get("max_price") or 0
        rng = f"${mn} – ${mx}" if mn or mx else "—"
        sc  = momentum_score(s)
        scores[name] = sc
        col = score_color(sc)
        bar_w = sc * 10
        rows_html += (
            f'<tr>'
            f'<td>{esc(name)}</td>'
            f'<td>{s["total_products"]}</td>'
            f'<td>{s["new_last_30d"]}</td>'
            f'<td>{esc(rng)}</td>'
            f'<td>'
            f'<span style="font-weight:700;color:{col};">{sc}/10</span>'
            f'<div style="height:4px;background:#e2e8f0;border-radius:2px;margin-top:4px;">'
            f'<div style="height:100%;background:{col};border-radius:2px;width:{bar_w}%;"></div>'
            f'</div>'
            f'</td>'
            f'</tr>'
        )

    sorted_s = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    leader_name,  leader_score  = sorted_s[0]
    second_name,  second_score  = sorted_s[1]
    leader_drops = stores[leader_name].get("new_last_30d", 0)
    no_drops     = [n for n, s in stores.items() if s.get("new_last_30d", 0) == 0]

    summary_parts = [
        f"{esc(leader_name)} leads with a momentum score of {leader_score}/10 "
        f"driven by {leader_drops} new drops.",
        f"{esc(second_name)} scores {second_score}/10.",
    ]
    if no_drops:
        nd_str = ", ".join(esc(n) for n in no_drops)
        summary_parts.append(
            f"{nd_str} show low activity with 0 new drops in the last 30 days."
        )
    summary_text = " ".join(summary_parts)

    return (
        f'<div class="page">'
        f'<div class="top-bar"></div>'
        f'<div class="content">'
        f'<div class="sh first">Market Momentum Scores</div>'
        f'<p style="font-size:10px;font-style:italic;color:#94a3b8;margin-bottom:14px;">'
        f'Momentum is calculated from new product activity, pricing range, and catalogue volume. Scored 1–10.'
        f'</p>'
        f'<table>'
        f'<thead><tr>'
        f'<th>Brand</th><th>Products</th><th>New Drops (30d)</th>'
        f'<th>Price Range</th><th>Momentum Score</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
        f'<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;">'
        f'<div style="background:#f8fafc;border-left:3px solid #f97316;border-radius:0 4px 4px 0;'
        f'padding:12px 14px;margin-top:16px;font-size:10px;color:#334155;line-height:1.6;">'
        f'<strong>Momentum Summary —</strong> {summary_text}'
        f'</div>'
        f'</div>'
        f'</div>'
        f'{footer_html(date_fmt, 2)}'
        f'</div>'
    )

# ── Page 3 — Competitor Breakdown ─────────────────────────────────────────────

def page3_html(metrics):
    date_str = metrics["date"]
    date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    stores   = metrics["stores"]
    tiers    = metrics.get("price_tiers", {})
    total_p  = metrics["total_products"]

    rows_html = ""
    for name, s in stores.items():
        mn        = s.get("min_price") or 0
        mx        = s.get("max_price") or 0
        avg       = f"${s['avg_price']}" if s.get("avg_price") else "—"
        rng       = f"${mn} – ${mx}" if mn or mx else "—"
        seg       = segment(s.get("avg_price"))
        seg_style = SEGMENT_STYLE.get(seg, "background:#f1f5f9;color:#334155;")
        cats      = s.get("top_product_types", [])[:3]
        cats_html = "".join(f'<span class="cat-pill">{esc(c)}</span>' for c in cats)
        rows_html += (
            f'<tr>'
            f'<td><strong>{esc(name)}</strong></td>'
            f'<td>{s["total_products"]}</td>'
            f'<td>{esc(avg)}</td>'
            f'<td>{esc(rng)}</td>'
            f'<td><span class="pill" style="{seg_style}">{esc(seg)}</span></td>'
            f'<td>{cats_html}</td>'
            f'</tr>'
        )

    tier_data = [
        ("Budget",    "< $25",    tiers.get("budget_under_25",    0)),
        ("Mid-Range", "$25–$50",  tiers.get("mid_25_to_50",       0)),
        ("Premium",   "$50–$100", tiers.get("premium_50_to_100",  0)),
        ("Luxury",    "$100+",    tiers.get("luxury_100_plus",    0)),
    ]
    tier_html = ""
    for label, range_str, count in tier_data:
        pct   = round(count / total_p * 100, 1) if total_p else 0
        bar_w = min(pct, 100)
        tier_html += (
            f'<div style="padding:8px 0;">'
            f'<div style="display:flex;justify-content:space-between;margin-bottom:5px;">'
            f'<span style="font-size:10px;color:#64748b;">{esc(label)} '
            f'<span style="color:#94a3b8;font-size:9px;">({esc(range_str)})</span></span>'
            f'<span style="font-size:10px;font-weight:700;color:#0f172a;">{pct}%</span>'
            f'</div>'
            f'<div style="height:6px;background:#e2e8f0;border-radius:3px;">'
            f'<div style="height:100%;background:#0f172a;border-radius:3px;width:{bar_w}%;"></div>'
            f'</div>'
            f'</div>'
        )

    mid_pct = round(tiers.get("mid_25_to_50", 0) / total_p * 100, 1) if total_p else 0
    lux_pct = round(tiers.get("luxury_100_plus", 0) / total_p * 100, 1) if total_p else 0
    price_summary = (
        f"Mid-range dominates at {mid_pct}% of tracked products. "
        f"Luxury represents only {lux_pct}%."
    )

    return (
        f'<div class="page">'
        f'<div class="top-bar"></div>'
        f'<div class="content">'
        f'<div class="sh first">Competitor Breakdown</div>'
        f'<table>'
        f'<thead><tr>'
        f'<th>Store</th><th>Products</th><th>Avg Price</th>'
        f'<th>Price Range</th><th>Segment</th><th>Top Categories</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
        f'<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;">'
        f'<div class="sh">Price Intelligence</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 24px;">'
        f'{tier_html}'
        f'</div>'
        f'<p style="font-size:10px;color:#94a3b8;font-style:italic;margin-top:12px;">'
        f'{esc(price_summary)}'
        f'</p>'
        f'</div>'
        f'</div>'
        f'{footer_html(date_fmt, 3)}'
        f'</div>'
    )

# ── Page 4 — New Launches + Category Intelligence ─────────────────────────────

def page4_html(metrics):
    date_str = metrics["date"]
    date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    stores   = metrics["stores"]

    launches_html = ""
    any_launches  = any(s["new_last_30d"] > 0 for s in stores.values())
    if not any_launches:
        launches_html = (
            '<p style="font-size:10px;color:#64748b;">'
            'No new products detected in this period.</p>'
        )
    else:
        for name, s in stores.items():
            if s["new_last_30d"] == 0:
                continue
            titles    = s.get("new_titles", [])
            avg_p     = s.get("avg_price")
            price_str = f"~${avg_p}" if avg_p else "—"
            shown     = titles[:5]
            remainder = len(titles) - 5

            product_rows = ""
            for t in shown:
                product_rows += (
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:5px 0;border-bottom:1px solid #f1f5f9;font-size:10px;">'
                    f'<span style="color:#334155;">{esc(t)}</span>'
                    f'<span style="color:#64748b;">{esc(price_str)}</span>'
                    f'</div>'
                )
            if remainder > 0:
                product_rows += (
                    f'<div style="font-size:9px;font-style:italic;color:#94a3b8;padding:5px 0;">'
                    f'+ {remainder} more</div>'
                )

            launches_html += (
                f'<div style="margin-bottom:14px;">'
                f'<div style="display:flex;align-items:center;gap:7px;margin-bottom:7px;">'
                f'<div style="width:6px;height:6px;border-radius:50%;background:#f97316;flex-shrink:0;"></div>'
                f'<span style="font-size:10px;font-weight:700;color:#0f172a;'
                f'text-transform:uppercase;letter-spacing:0.05em;">{esc(name)}</span>'
                f'</div>'
                f'{product_rows}'
                f'</div>'
            )

    cats      = category_counts(metrics)
    max_count = cats[0][1] if cats else 1
    cat_html  = ""
    for cat, count in cats:
        pct = round(count / max_count * 100)
        cat_html += (
            f'<div style="display:flex;align-items:center;gap:10px;'
            f'padding:5px 0;border-bottom:1px solid #f1f5f9;">'
            f'<span style="width:130px;font-size:10px;color:#334155;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{esc(cat)}</span>'
            f'<div style="flex:1;height:5px;background:#e2e8f0;border-radius:3px;">'
            f'<div style="height:100%;background:#0f172a;border-radius:3px;width:{pct}%;"></div>'
            f'</div>'
            f'<span style="font-size:10px;color:#64748b;width:20px;text-align:right;">{count}</span>'
            f'</div>'
        )
    cat_most  = cats[0][0]  if cats else "—"
    cat_least = cats[-1][0] if len(cats) > 1 else "—"
    cat_summary = (
        f"Most represented: {esc(cat_most)} · "
        f"Least represented (potential gap): {esc(cat_least)}"
    )

    return (
        f'<div class="page">'
        f'<div class="top-bar"></div>'
        f'<div class="content">'
        f'<div class="sh first">New Launches — Last 30 Days</div>'
        f'{launches_html}'
        f'<div class="sh">Category Intelligence</div>'
        f'<div style="margin-bottom:12px;">{cat_html}</div>'
        f'<p style="font-size:10px;font-style:italic;color:#94a3b8;">{cat_summary}</p>'
        f'</div>'
        f'{footer_html(date_fmt, 4)}'
        f'</div>'
    )

# ── Page 5 — Areas to Watch ───────────────────────────────────────────────────

CONFIDENCE_BADGE = {
    "HIGH":    "background:#dcfce7;color:#166534;",
    "MEDIUM":  "background:#dbeafe;color:#1e40af;",
    "LOW":     "background:#fef3c7;color:#92400e;",
    "MONITOR": "background:#f1f5f9;color:#475569;",
}


def page5_html(metrics, md, agent3=None):
    date_str     = metrics["date"]
    date_fmt     = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    suggestions  = parse_advisor_suggestions(agent3)
    dq_warnings  = (agent3 or {}).get("data_quality_warnings", [])

    # ── Suggestion cards ──────────────────────────────────────────────────────
    if suggestions:
        cards_html = ""
        for i, s in enumerate(suggestions, 1):
            badge_key   = "MONITOR" if s["is_monitor"] else s["confidence"]
            badge_style = CONFIDENCE_BADGE.get(badge_key, CONFIDENCE_BADGE["MONITOR"])
            badge_label = f"MONITOR · {s['confidence']}" if s["is_monitor"] else s["confidence"]

            citation_html = ""
            if s["data_citation"]:
                citation_html = (
                    f'<div style="font-size:9px;color:#94a3b8;font-style:italic;'
                    f'margin-top:6px;line-height:1.5;">'
                    f'Data: {esc(s["data_citation"])}'
                    f'</div>'
                )

            cards_html += (
                f'<div style="border:1px solid #e2e8f0;border-radius:8px;padding:18px 20px;'
                f'display:flex;gap:20px;flex:1;background:white;align-items:flex-start;">'
                f'<div style="font-size:40px;font-weight:700;color:#f97316;line-height:1;'
                f'min-width:40px;padding-top:4px;">{i}</div>'
                f'<div style="width:1px;background:#f1f5f9;align-self:stretch;flex-shrink:0;"></div>'
                f'<div style="display:flex;flex-direction:column;justify-content:center;'
                f'padding-left:4px;flex:1;">'
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'
                f'<div style="font-size:12px;font-weight:700;color:#0f172a;">{esc(s["title"])}</div>'
                f'<span class="pill" style="{badge_style}font-size:8px;font-weight:700;">'
                f'{esc(badge_label)}</span>'
                f'</div>'
                f'<div style="font-size:10px;color:#64748b;line-height:1.7;">{esc(s["body"])}</div>'
                f'{citation_html}'
                f'</div>'
                f'</div>'
            )
    else:
        # Fallback to old markdown parser
        actions    = parse_actions(md, count=3)
        cards_html = ""
        for i, (title, body) in enumerate(actions, 1):
            cards_html += (
                f'<div style="border:1px solid #e2e8f0;border-radius:8px;padding:22px 20px;'
                f'display:flex;gap:20px;flex:1;background:white;align-items:flex-start;">'
                f'<div style="font-size:44px;font-weight:700;color:#f97316;line-height:1;'
                f'min-width:44px;padding-top:4px;">{i}</div>'
                f'<div style="width:1px;background:#f1f5f9;align-self:stretch;flex-shrink:0;"></div>'
                f'<div style="display:flex;flex-direction:column;justify-content:center;padding-left:4px;">'
                f'<div style="font-size:12px;font-weight:700;color:#0f172a;margin-bottom:8px;">'
                f'{esc(title)}</div>'
                f'<div style="font-size:11px;color:#64748b;line-height:1.8;">{esc(body)}</div>'
                f'</div>'
                f'</div>'
            )

    # ── Data Notes section ────────────────────────────────────────────────────
    data_notes_html = ""
    if dq_warnings:
        items = "".join(
            f'<li style="margin-bottom:4px;">{esc(w)}</li>'
            for w in dq_warnings
        )
        data_notes_html = (
            f'<div class="sh" style="margin-top:16px;">Data Notes</div>'
            f'<ul style="padding-left:16px;font-size:9px;color:#64748b;line-height:1.6;">'
            f'{items}'
            f'</ul>'
        )

    return (
        f'<div class="page" style="height:297mm;">'
        f'<div class="top-bar"></div>'
        f'<div class="content" style="padding-bottom:52px;">'
        f'<div class="sh first">3 Areas to Watch Today</div>'
        f'<p style="font-size:10px;font-style:italic;color:#94a3b8;margin-bottom:14px;">'
        f'The following patterns were flagged by AI analysis of today\'s market data.'
        f'</p>'
        f'<div style="display:flex;flex-direction:column;gap:10px;">'
        f'{cards_html}'
        f'</div>'
        f'{data_notes_html}'
        f'<p style="text-align:center;font-size:9px;color:#94a3b8;margin-top:14px;">'
        f'Candle Intel · Automated competitor intelligence · '
        f'Strategic decisions remain with your team.'
        f'</p>'
        f'</div>'
        f'{footer_html(date_fmt, 5)}'
        f'</div>'
    )

# ── HTML Builder ──────────────────────────────────────────────────────────────

def build_html(metrics, md, agent3=None):
    pages = "\n".join([
        page1_html(metrics, md, agent3),
        page2_html(metrics),
        page3_html(metrics),
        page4_html(metrics),
        page5_html(metrics, md, agent3),
    ])
    return (
        f'<!DOCTYPE html>\n'
        f'<html lang="en">\n'
        f'<head>\n'
        f'<meta charset="UTF-8"/>\n'
        f'<style>{CSS}</style>\n'
        f'</head>\n'
        f'<body>\n'
        f'{pages}\n'
        f'</body>\n'
        f'</html>'
    )

# ── PDF Builder ───────────────────────────────────────────────────────────────

def build_pdf(metrics, md, agent3=None):
    date_str = metrics["date"]
    out_path = str(Path("reports") / f"report_{date_str}.pdf")
    html_str = build_html(metrics, md, agent3)

    with open("reports/preview.html", "w", encoding="utf-8") as f:
        f.write(html_str)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context()
        pw_page = context.new_page()
        pw_page.emulate_media(media="print")
        pw_page.set_content(html_str, wait_until="networkidle")
        pw_page.wait_for_timeout(1000)
        pw_page.pdf(
            path=out_path,
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()

    return out_path

# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*60}")
    print("  AGENT 4 -- PDF REPORT GENERATOR (Playwright)")
    print(f"{'='*60}\n")

    metrics, md, agent3 = load_latest()
    print(f"  Loaded metrics for {metrics['date']}")
    if agent3:
        print(f"  Loaded agent3 output (run_date: {agent3.get('run_date')})")
    print("  Rendering HTML -> PDF via Chromium...")

    pdf_path = build_pdf(metrics, md, agent3)
    abs_path = str(Path(pdf_path).resolve())

    print(f"  Saved: {pdf_path}")
    print(f"\n  PDF path: {abs_path}\n")
    return pdf_path


if __name__ == "__main__":
    run()
