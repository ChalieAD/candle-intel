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

def score_cls(score):
    if score >= 8: return "high"
    if score >= 5: return "medium"
    return "low"

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

SEGMENT_BADGE = {
    "Budget":    "badge--budget",
    "Mid-Range": "badge--midrange",
    "Premium":   "badge--premium",
    "Luxury":    "badge--luxury",
    "—":         "",
}

CONFIDENCE_BADGE_CLS = {
    "HIGH":    "badge--high",
    "MEDIUM":  "badge--medium",
    "LOW":     "badge--low",
    "MONITOR": "badge--monitor",
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

    # Headers may appear bare, with ## prefix, or wrapped in **bold**
    _sec = r"(?:#{1,3}\s*)?(?:\*{1,2})?"
    _end = r"(?:\*{1,2})?"
    happened_m = re.search(
        rf"{_sec}WHAT HAPPENED TODAY{_end}\s*\n(.+?)(?=\n{_sec}WHAT IT MEANS FOR YOU|\n{_sec}YOUR 3|\n{_sec}DATA NOTES|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    means_m = re.search(
        rf"{_sec}WHAT IT MEANS FOR YOU{_end}\s*\n(.+?)(?=\n{_sec}YOUR 3|\n{_sec}DATA NOTES|\Z)",
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
            "confidence":    confidence,
            "is_monitor":    is_monitor,
            "data_citation": data_citation,
            "body":          body,
            "title":         title,
        })

    return results if results else None


def category_counts(metrics):
    """
    Count total products per category across all stores.
    Each store's top_product_types list is ranked — we weight by store's
    total_products split evenly across its listed types, so bar widths
    reflect actual product volume rather than store count.
    """
    counter = Counter()
    for s in metrics["stores"].values():
        types = s.get("top_product_types", [])
        total = s.get("total_products", 0)
        if not types or not total:
            continue
        per_type = total / len(types)
        for pt in types:
            counter[pt] += per_type
    # Round to ints for display
    return [(cat, int(round(count))) for cat, count in counter.most_common(12)]

# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=DM+Serif+Display&display=swap');

@page {
    size: A4;
    margin: 0;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

html, body {
    font-family: 'DM Sans', sans-serif;
    font-size: 10pt;
    line-height: 1.55;
    color: #0c1220;
    background: #f8f9fb;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}

.page {
    width: 210mm;
    height: 297mm;
    padding: 20mm 22mm 18mm 22mm;
    background: #f8f9fb;
    position: relative;
    overflow: hidden;
    page-break-after: always;
    display: flex;
    flex-direction: column;
}

.page:last-child {
    page-break-after: avoid;
}

.report-header {
    background: #0c1220;
    padding: 22px 28px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-radius: 6px;
    margin-bottom: 20px;
}

.report-header .brand-name {
    font-family: 'DM Serif Display', serif;
    font-size: 22pt;
    color: #ffffff;
    letter-spacing: 0.5px;
}

.report-header .brand-subtitle {
    font-family: 'DM Sans', sans-serif;
    font-size: 8pt;
    color: #94a3b8;
    letter-spacing: 2px;
    text-transform: uppercase;
    font-weight: 500;
    margin-top: 2px;
}

.report-header .report-date {
    font-family: 'DM Sans', sans-serif;
    font-size: 9pt;
    color: #94a3b8;
    text-align: right;
    font-weight: 500;
}

.section-heading {
    font-family: 'DM Serif Display', serif;
    font-size: 14pt;
    color: #0c1220;
    margin-bottom: 4px;
    letter-spacing: 0.3px;
}

.section-heading-bar {
    width: 40px;
    height: 3px;
    background: #e8762a;
    border-radius: 2px;
    margin-bottom: 16px;
}

.metrics-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-bottom: 20px;
}

.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 0;
    overflow: hidden;
}

.metric-card-inner {
    padding: 16px 20px;
}

.metric-card .metric-value {
    font-family: 'DM Serif Display', serif;
    font-size: 28pt;
    color: #0c1220;
    line-height: 1.1;
    margin-bottom: 4px;
}

.metric-card .metric-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 7pt;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 1.8px;
    font-weight: 600;
}

.metric-card--primary {
    border-top: 3px solid #e8762a;
}

.metric-card--secondary {
    border-top: 3px solid #0c1220;
}

.insight-box {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 18px 22px;
    margin-bottom: 14px;
    position: relative;
}

.insight-box::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 4px;
    height: 100%;
    border-radius: 6px 0 0 6px;
}

.insight-box--alert::before {
    background: #e8762a;
}

.insight-box--context::before {
    background: #2563eb;
}

.insight-box .insight-heading {
    font-family: 'DM Sans', sans-serif;
    font-size: 8pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #475569;
    margin-bottom: 8px;
}

.insight-box .insight-text {
    font-family: 'DM Sans', sans-serif;
    font-size: 9.5pt;
    line-height: 1.6;
    color: #1e293b;
}

.data-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    overflow: hidden;
    margin-bottom: 16px;
    font-size: 9pt;
}

.data-table thead {
    background: #141c2e;
}

.data-table thead th {
    font-family: 'DM Sans', sans-serif;
    font-size: 7.5pt;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: #ffffff;
    padding: 10px 14px;
    text-align: left;
    border-bottom: none;
}

.data-table tbody tr {
    border-bottom: 1px solid #f1f5f9;
}

.data-table tbody tr:last-child {
    border-bottom: none;
}

.data-table tbody tr:nth-child(even) {
    background: #f8f9fb;
}

.data-table tbody td {
    padding: 10px 14px;
    font-family: 'DM Sans', sans-serif;
    font-size: 9pt;
    color: #1e293b;
    vertical-align: middle;
}

.data-table .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    font-weight: 500;
}

.momentum-bar-container {
    display: flex;
    align-items: center;
    gap: 8px;
}

.momentum-score-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 10pt;
    font-weight: 700;
    min-width: 32px;
}

.momentum-bar-track {
    flex: 1;
    height: 6px;
    background: #e2e8f0;
    border-radius: 3px;
    overflow: hidden;
}

.momentum-bar-fill {
    height: 100%;
    border-radius: 3px;
}

.momentum-bar-fill.score-high    { background: #16a34a; }
.momentum-bar-fill.score-medium  { background: #e8762a; }
.momentum-bar-fill.score-low     { background: #94a3b8; }

.score-text-high   { color: #16a34a; }
.score-text-medium { color: #e8762a; }
.score-text-low    { color: #475569; }

.badge {
    display: inline-block;
    font-family: 'DM Sans', sans-serif;
    font-size: 7pt;
    font-weight: 600;
    letter-spacing: 0.5px;
    padding: 3px 10px;
    border-radius: 12px;
    text-transform: uppercase;
}

.badge--budget   { background: #dbeafe; color: #1e40af; }
.badge--midrange { background: #fef3c7; color: #92400e; }
.badge--premium  { background: #fce7f3; color: #9d174d; }
.badge--luxury   { background: #f3e8ff; color: #6b21a8; }

.badge--high    { background: #dc2626; color: #ffffff; font-size: 6.5pt; padding: 2px 10px; }
.badge--medium  { background: #d97706; color: #ffffff; font-size: 6.5pt; padding: 2px 10px; }
.badge--low     { background: #64748b; color: #ffffff; font-size: 6.5pt; padding: 2px 10px; }
.badge--monitor { background: #2563eb; color: #ffffff; font-size: 6.5pt; padding: 2px 10px; }

.category-tag {
    display: inline-block;
    font-family: 'DM Sans', sans-serif;
    font-size: 7pt;
    color: #475569;
    background: #f1f5f9;
    padding: 2px 8px;
    border-radius: 3px;
    margin-right: 4px;
    margin-bottom: 2px;
}

.price-dist-row {
    display: flex;
    align-items: center;
    margin-bottom: 8px;
}

.price-dist-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 8.5pt;
    color: #475569;
    width: 140px;
    flex-shrink: 0;
}

.price-dist-bar-track {
    flex: 1;
    height: 8px;
    background: #e2e8f0;
    border-radius: 4px;
    overflow: hidden;
    margin: 0 10px;
}

.price-dist-bar-fill {
    height: 100%;
    background: #0c1220;
    border-radius: 4px;
}

.price-dist-value {
    font-family: 'DM Sans', sans-serif;
    font-size: 9pt;
    font-weight: 700;
    color: #0c1220;
    width: 50px;
    text-align: right;
}

.launches-brand-header {
    font-family: 'DM Sans', sans-serif;
    font-size: 8pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #0c1220;
    padding: 10px 0 6px 0;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 6px;
}

.launches-brand-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}

.launches-product-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 5px 0 5px 14px;
    font-size: 9pt;
    color: #1e293b;
}

.launches-product-row .product-price {
    font-weight: 600;
    color: #475569;
    font-variant-numeric: tabular-nums;
}

.launches-more {
    font-size: 8pt;
    color: #94a3b8;
    padding-left: 14px;
    font-style: italic;
    margin-bottom: 10px;
}

.cat-intel-row {
    display: flex;
    align-items: center;
    margin-bottom: 6px;
}

.cat-intel-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 8.5pt;
    color: #1e293b;
    width: 120px;
    flex-shrink: 0;
}

.cat-intel-bar-track {
    flex: 1;
    height: 8px;
    background: #e2e8f0;
    border-radius: 4px;
    overflow: hidden;
    margin: 0 10px;
}

.cat-intel-bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #0c1220, #1a2540);
    border-radius: 4px;
}

.cat-intel-value {
    font-family: 'DM Sans', sans-serif;
    font-size: 9pt;
    font-weight: 700;
    color: #0c1220;
    width: 30px;
    text-align: right;
}

.callout-dark {
    background: #0c1220;
    border-radius: 6px;
    padding: 18px 22px;
    margin: 14px 0;
}

.callout-dark p {
    font-family: 'DM Sans', sans-serif;
    font-size: 9.5pt;
    line-height: 1.65;
    color: #e2e8f0;
}

.callout-dark strong {
    color: #ffffff;
    font-weight: 600;
}

.score-strip {
    display: flex;
    gap: 10px;
    margin: 14px 0;
}

.score-strip-item {
    flex: 1;
    text-align: center;
    padding: 12px 8px;
    border-radius: 6px;
    background: #141c2e;
}

.score-strip-item .score-number {
    font-family: 'DM Serif Display', serif;
    font-size: 20pt;
    line-height: 1;
    margin-bottom: 4px;
}

.score-strip-item .score-brand {
    font-family: 'DM Sans', sans-serif;
    font-size: 7pt;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.score-strip-item.rank-1 .score-number { color: #16a34a; }
.score-strip-item.rank-2 .score-number { color: #e8762a; }
.score-strip-item.rank-3 .score-number { color: #94a3b8; }
.score-strip-item.rank-4 .score-number { color: #94a3b8; }
.score-strip-item.rank-5 .score-number { color: #64748b; }

.watch-section-intro {
    font-family: 'DM Sans', sans-serif;
    font-size: 8.5pt;
    color: #64748b;
    margin-bottom: 18px;
    line-height: 1.5;
}

.watch-card {
    display: flex;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    overflow: hidden;
    margin-bottom: 14px;
    min-height: 120px;
}

.watch-card-rank {
    width: 56px;
    background: #0c1220;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 18px;
    flex-shrink: 0;
}

.watch-card-rank .rank-number {
    font-family: 'DM Serif Display', serif;
    font-size: 24pt;
    color: #e8762a;
    line-height: 1;
}

.watch-card-body {
    flex: 1;
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    justify-content: center;
}

.watch-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 8px;
    gap: 12px;
}

.watch-card-title {
    font-family: 'DM Sans', sans-serif;
    font-size: 10.5pt;
    font-weight: 700;
    color: #0c1220;
    line-height: 1.35;
    flex: 1;
}

.watch-card-text {
    font-family: 'DM Sans', sans-serif;
    font-size: 9pt;
    color: #475569;
    line-height: 1.55;
    margin-bottom: 10px;
}

.watch-card-evidence-alt {
    font-family: 'DM Sans', sans-serif;
    font-size: 7.5pt;
    color: #94a3b8;
    border-top: 1px solid #f1f5f9;
    padding-top: 8px;
}

.watch-card-evidence-alt .evidence-label {
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-size: 6.5pt;
    margin-right: 4px;
}

.market-overview-box {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 0;
    margin-bottom: 18px;
    overflow: hidden;
}

.market-overview-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 20px;
    border-bottom: 1px solid #f1f5f9;
}

.market-overview-row:last-child {
    border-bottom: none;
}

.market-overview-row .overview-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 9pt;
    color: #64748b;
}

.market-overview-row .overview-value {
    font-family: 'DM Sans', sans-serif;
    font-size: 9.5pt;
    font-weight: 700;
    color: #0c1220;
}

.page-footer {
    margin-top: auto;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 12px;
    border-top: 1px solid #e2e8f0;
}

.page-footer .footer-brand {
    font-family: 'DM Sans', sans-serif;
    font-size: 7pt;
    color: #94a3b8;
    letter-spacing: 0.5px;
}

.page-footer .footer-page {
    font-family: 'DM Sans', sans-serif;
    font-size: 7pt;
    color: #94a3b8;
}

.mt-0  { margin-top: 0; }
.mt-8  { margin-top: 8px; }
.mt-12 { margin-top: 12px; }
.mt-16 { margin-top: 16px; }
.mt-20 { margin-top: 20px; }
.mb-0  { margin-bottom: 0; }
.mb-8  { margin-bottom: 8px; }
.mb-12 { margin-bottom: 12px; }
.mb-16 { margin-bottom: 16px; }
.mb-20 { margin-bottom: 20px; }

.text-muted     { color: #94a3b8; }
.text-secondary { color: #475569; }
.font-bold      { font-weight: 700; }
.font-medium    { font-weight: 500; }

.flex-grow { flex: 1; }
.flex-col  { display: flex; flex-direction: column; }

.section-fill {
    flex: 1;
    display: flex;
    flex-direction: column;
}
"""

# ── Shared components ─────────────────────────────────────────────────────────

def footer_html(date_fmt, page_num):
    return (
        f'<div class="page-footer">'
        f'<span class="footer-brand">Candle Intel · Daily Intelligence Report</span>'
        f'<span class="footer-page">{esc(date_fmt)} · Page {page_num}</span>'
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
            f'<div class="metric-card metric-card--primary">'
            f'<div class="metric-card-inner">'
            f'<div class="metric-value">{esc(val)}</div>'
            f'<div class="metric-label">{esc(label)}</div>'
            f'</div>'
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
            f'<div class="market-overview-row">'
            f'<span class="overview-label">{esc(label)}</span>'
            f'<span class="overview-value">{value}</span>'
            f'</div>'
        )

    if writer_p1:
        insight_html = (
            f'<div class="insight-box insight-box--alert">'
            f'<div class="insight-text">{esc(writer_p1["happened"])}</div>'
            f'</div>'
            f'<div class="section-heading mt-20">What It Means For You</div>'
            f'<div class="section-heading-bar"></div>'
            f'<div class="insight-box insight-box--context">'
            f'<div class="insight-text">{esc(writer_p1["means"])}</div>'
            f'</div>'
        )
    else:
        insight_html = (
            f'<div class="insight-box insight-box--alert">'
            f'<div class="insight-text">{esc(parse_snapshot(md))}</div>'
            f'</div>'
        )

    return (
        f'<div class="page">'
        f'<div class="report-header">'
        f'<div>'
        f'<div class="brand-name">CANDLE INTEL</div>'
        f'<div class="brand-subtitle">Daily Intelligence Report</div>'
        f'</div>'
        f'<div class="report-date">{esc(date_fmt)}</div>'
        f'</div>'
        f'<div class="section-heading">Today\'s Metrics</div>'
        f'<div class="section-heading-bar"></div>'
        f'<div class="metrics-grid">{kpi_html}</div>'
        f'<div class="section-heading mt-20">What Happened Today</div>'
        f'<div class="section-heading-bar"></div>'
        f'{insight_html}'
        f'<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;">'
        f'<div class="section-heading mt-20">Market Overview</div>'
        f'<div class="section-heading-bar"></div>'
        f'<div class="market-overview-box">{overview_html}</div>'
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
        bar_w = sc * 10
        cls   = score_cls(sc)
        rows_html += (
            f'<tr>'
            f'<td>{esc(name)}</td>'
            f'<td class="num">{s["total_products"]}</td>'
            f'<td class="num">{s["new_last_30d"]}</td>'
            f'<td>{esc(rng)}</td>'
            f'<td>'
            f'<div class="momentum-bar-container">'
            f'<span class="momentum-score-label score-text-{cls}">{sc}/10</span>'
            f'<div class="momentum-bar-track">'
            f'<div class="momentum-bar-fill score-{cls}" style="width:{bar_w}%;"></div>'
            f'</div>'
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

    score_tiles = ""
    for idx, (name, sc) in enumerate(
        sorted(scores.items(), key=lambda x: x[1], reverse=True), 1
    ):
        score_tiles += (
            f'<div class="score-strip-item rank-{idx}">'
            f'<div class="score-number">{sc}/10</div>'
            f'<div class="score-brand">{esc(name)}</div>'
            f'</div>'
        )

    return (
        f'<div class="page">'
        f'<div class="section-heading">Market Momentum Scores</div>'
        f'<div class="section-heading-bar"></div>'
        f'<p class="watch-section-intro">'
        f'Momentum is calculated from new product activity, pricing range, and catalogue volume. Scored 1–10.'
        f'</p>'
        f'<table class="data-table">'
        f'<thead><tr>'
        f'<th>Brand</th><th>Products</th><th>New Drops (30d)</th>'
        f'<th>Price Range</th><th>Momentum Score</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
        f'<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;">'
        f'<div class="section-heading mt-20">What This Means</div>'
        f'<div class="section-heading-bar"></div>'
        f'<div class="callout-dark">'
        f'<p>{summary_text}</p>'
        f'<div class="score-strip mt-12">{score_tiles}</div>'
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
        badge_cls = SEGMENT_BADGE.get(seg, "")
        cats      = s.get("top_product_types", [])[:3]
        cats_html = "".join(f'<span class="category-tag">{esc(c)}</span>' for c in cats)
        badge_html = (
            f'<span class="badge {badge_cls}">{esc(seg)}</span>'
            if badge_cls else esc(seg)
        )
        rows_html += (
            f'<tr>'
            f'<td><strong>{esc(name)}</strong></td>'
            f'<td class="num">{s["total_products"]}</td>'
            f'<td class="num">{esc(avg)}</td>'
            f'<td>{esc(rng)}</td>'
            f'<td>{badge_html}</td>'
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
            f'<div class="price-dist-row">'
            f'<div class="price-dist-label">'
            f'{esc(label)} <span style="color:#94a3b8;font-size:8pt;">({esc(range_str)})</span>'
            f'</div>'
            f'<div class="price-dist-bar-track">'
            f'<div class="price-dist-bar-fill" style="width:{bar_w}%;"></div>'
            f'</div>'
            f'<div class="price-dist-value">{pct}%</div>'
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
        f'<div class="section-heading">Competitor Breakdown</div>'
        f'<div class="section-heading-bar"></div>'
        f'<table class="data-table">'
        f'<thead><tr>'
        f'<th>Store</th><th>Products</th><th>Avg Price</th>'
        f'<th>Price Range</th><th>Segment</th><th>Top Categories</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
        f'<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;">'
        f'<div class="section-heading mt-20">Price Intelligence</div>'
        f'<div class="section-heading-bar"></div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 24px;">'
        f'{tier_html}'
        f'</div>'
        f'<p class="text-muted mt-12">{esc(price_summary)}</p>'
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
            '<p class="text-secondary" style="font-size:9.5pt;">'
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
                    f'<div class="launches-product-row">'
                    f'<span>{esc(t)}</span>'
                    f'<span class="product-price">{esc(price_str)}</span>'
                    f'</div>'
                )
            if remainder > 0:
                product_rows += (
                    f'<div class="launches-more">+ {remainder} more</div>'
                )

            launches_html += (
                f'<div style="margin-bottom:14px;">'
                f'<div class="launches-brand-header">'
                f'<span class="launches-brand-dot" style="background:#e8762a;"></span>'
                f'{esc(name)}'
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
            f'<div class="cat-intel-row">'
            f'<span class="cat-intel-label">{esc(cat)}</span>'
            f'<div class="cat-intel-bar-track">'
            f'<div class="cat-intel-bar-fill" style="width:{pct}%;"></div>'
            f'</div>'
            f'<span class="cat-intel-value">{count}</span>'
            f'</div>'
        )
    cat_most       = cats[0][0]  if cats else "—"
    cat_most_count = cats[0][1]  if cats else 0
    cat_least      = cats[-1][0] if len(cats) > 1 else "—"
    cat_insight = (
        f"{esc(cat_most)} dominates with {cat_most_count} products across tracked brands. "
        f"{esc(cat_least)} has the lowest representation — a potential gap worth exploring."
    )

    return (
        f'<div class="page">'
        f'<div class="section-heading">New Launches — Last 30 Days</div>'
        f'<div class="section-heading-bar"></div>'
        f'{launches_html}'
        f'<div class="section-heading mt-20">Category Intelligence</div>'
        f'<div class="section-heading-bar"></div>'
        f'<div style="margin-bottom:16px;">{cat_html}</div>'
        f'<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;">'
        f'<div class="callout-dark"><p>{cat_insight}</p></div>'
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
            badge_cls   = CONFIDENCE_BADGE_CLS.get(badge_key, "badge--monitor")
            badge_label = f"MONITOR · {s['confidence']}" if s["is_monitor"] else s["confidence"]

            citation_html = ""
            if s["data_citation"]:
                citation_html = (
                    f'<div class="watch-card-evidence-alt">'
                    f'<span class="evidence-label">Data:</span>'
                    f'{esc(s["data_citation"])}'
                    f'</div>'
                )

            cards_html += (
                f'<div class="watch-card">'
                f'<div class="watch-card-rank">'
                f'<span class="rank-number">{i}</span>'
                f'</div>'
                f'<div class="watch-card-body">'
                f'<div class="watch-card-header">'
                f'<div class="watch-card-title">{esc(s["title"])}</div>'
                f'<span class="badge {badge_cls}">{esc(badge_label)}</span>'
                f'</div>'
                f'<div class="watch-card-text">{esc(s["body"])}</div>'
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
                f'<div class="watch-card">'
                f'<div class="watch-card-rank">'
                f'<span class="rank-number">{i}</span>'
                f'</div>'
                f'<div class="watch-card-body">'
                f'<div class="watch-card-header">'
                f'<div class="watch-card-title">{esc(title)}</div>'
                f'</div>'
                f'<div class="watch-card-text">{esc(body)}</div>'
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
            f'<div class="section-heading mt-16">Data Notes</div>'
            f'<div class="section-heading-bar"></div>'
            f'<ul style="padding-left:16px;font-size:8pt;color:#64748b;line-height:1.6;">'
            f'{items}'
            f'</ul>'
        )

    return (
        f'<div class="page" style="height:297mm;">'
        f'<div class="section-heading">3 Areas to Watch Today</div>'
        f'<div class="section-heading-bar"></div>'
        f'<p class="watch-section-intro">'
        f'The following patterns were flagged by AI analysis of today\'s market data.'
        f'</p>'
        f'<div style="flex:1;display:flex;flex-direction:column;gap:10px;">'
        f'{cards_html}'
        f'</div>'
        f'{data_notes_html}'
        f'<p class="text-muted mt-16" style="text-align:center;font-size:8pt;">'
        f'Candle Intel · Automated competitor intelligence · '
        f'Strategic decisions remain with your team.'
        f'</p>'
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
