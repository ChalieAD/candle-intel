"""
Agent 4 — HTML Report Generator
Reads the markdown report + metrics JSON and produces a
beautiful, self-contained HTML report.
"""

import json
from datetime import datetime
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_latest(reports_dir: str = "reports"):
    p = Path(reports_dir)
    md_files   = sorted(p.glob("report_*.md"),   reverse=True)
    json_files = sorted(p.glob("metrics_*.json"), reverse=True)
    if not md_files or not json_files:
        raise FileNotFoundError("No report/metrics files found in reports/")
    with open(md_files[0],   encoding="utf-8") as f:
        md = f.read()
    with open(json_files[0]) as f:
        metrics = json.load(f)
    return md, metrics


def tier_pct(count, total):
    return round(count / total * 100) if total else 0


# ── HTML Builder ──────────────────────────────────────────────────────────────

def build_html(md: str, m: dict) -> str:
    stores   = m["stores"]
    tiers    = m["price_tiers"]
    total_p  = m["total_products"]
    date_fmt = datetime.strptime(m["date"], "%Y-%m-%d").strftime("%B %d, %Y")

    # ── KPI cards ────────────────────────────────────────────────────────────
    total_new = sum(s["new_last_30d"] for s in stores.values())
    avg_prices = [s["avg_price"] for s in stores.values() if s["avg_price"]]
    market_avg = round(sum(avg_prices) / len(avg_prices), 2)
    most_active = max(stores.items(), key=lambda x: x[1]["new_last_30d"])

    kpi_cards = f"""
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-value">{total_p}</div>
        <div class="kpi-label">Products Tracked</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{m['total_stores']}</div>
        <div class="kpi-label">Competitors</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{total_new}</div>
        <div class="kpi-label">New Drops (30d)</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">${market_avg}</div>
        <div class="kpi-label">Market Avg Price</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{most_active[0].split()[0]}</div>
        <div class="kpi-label">Most Active Store</div>
      </div>
    </div>"""

    # ── Competitor comparison table ───────────────────────────────────────────
    store_rows = ""
    tier_labels = {
        "budget_under_25":   ("Budget", "#10b981"),
        "mid_25_to_50":      ("Mid-Range", "#3b82f6"),
        "premium_50_to_100": ("Premium", "#8b5cf6"),
        "luxury_100_plus":   ("Luxury", "#f59e0b"),
    }

    positioning = {
        "P.F. Candle Co.": ("Mid-Range", "#3b82f6"),
        "Keap Candles":    ("Luxury",    "#f59e0b"),
        "Homesick":        ("Budget",    "#10b981"),
        "Otherland":       ("Mid-Range", "#3b82f6"),
        "Boy Smells":      ("Premium",   "#8b5cf6"),
    }

    activity_bar_colors = ["#f97316", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6"]
    max_new = max((s["new_last_30d"] for s in stores.values()), default=1) or 1

    for i, (name, s) in enumerate(stores.items()):
        pos_label, pos_color = positioning.get(name, ("Mid-Range", "#3b82f6"))
        bar_color = activity_bar_colors[i % len(activity_bar_colors)]
        bar_width = round(s["new_last_30d"] / max_new * 100)
        types_html = " ".join(
            f'<span class="tag">{t}</span>' for t in s["top_product_types"][:3]
        )
        store_rows += f"""
        <tr>
          <td>
            <div class="store-name">{name}</div>
            <a href="{s['url']}" class="store-url" target="_blank">{s['url'].replace('https://','')}</a>
          </td>
          <td class="num">{s['total_products']}</td>
          <td class="num">${s['avg_price']}</td>
          <td class="num">${s['min_price']} – ${s['max_price']}</td>
          <td>
            <div class="bar-wrap">
              <div class="bar" style="width:{bar_width}%;background:{bar_color}"></div>
              <span class="bar-label">{s['new_last_30d']}</span>
            </div>
          </td>
          <td><span class="badge" style="background:{pos_color}22;color:{pos_color};border:1px solid {pos_color}66">{pos_label}</span></td>
          <td>{types_html}</td>
        </tr>"""

    comp_table = f"""
    <table class="comp-table">
      <thead>
        <tr>
          <th>Store</th>
          <th>Products</th>
          <th>Avg Price</th>
          <th>Price Range</th>
          <th>New Drops (30d)</th>
          <th>Segment</th>
          <th>Top Categories</th>
        </tr>
      </thead>
      <tbody>
        {store_rows}
      </tbody>
    </table>"""

    # ── Price tier donut ──────────────────────────────────────────────────────
    tier_data = [
        (tiers["budget_under_25"],   "Under $25",   "#10b981"),
        (tiers["mid_25_to_50"],      "$25 – $50",   "#3b82f6"),
        (tiers["premium_50_to_100"], "$50 – $100",  "#8b5cf6"),
        (tiers["luxury_100_plus"],   "$100+",        "#f59e0b"),
    ]
    tier_legend = "".join(
        f'<div class="legend-item"><span class="dot" style="background:{c}"></span>{label} <strong>{tier_pct(n, total_p)}%</strong> ({n})</div>'
        for n, label, c in tier_data
    )

    # SVG donut chart (pure SVG, no JS)
    cx, cy, r_out, r_in = 90, 90, 80, 50
    import math
    def donut_path(pct_start, pct_end, color):
        a1 = 2 * math.pi * pct_start - math.pi / 2
        a2 = 2 * math.pi * pct_end   - math.pi / 2
        large = 1 if (pct_end - pct_start) > 0.5 else 0
        x1o, y1o = cx + r_out * math.cos(a1), cy + r_out * math.sin(a1)
        x2o, y2o = cx + r_out * math.cos(a2), cy + r_out * math.sin(a2)
        x1i, y1i = cx + r_in  * math.cos(a2), cy + r_in  * math.sin(a2)
        x2i, y2i = cx + r_in  * math.cos(a1), cy + r_in  * math.sin(a1)
        return (f'<path d="M {x1o:.1f} {y1o:.1f} A {r_out} {r_out} 0 {large} 1 {x2o:.1f} {y2o:.1f} '
                f'L {x1i:.1f} {y1i:.1f} A {r_in} {r_in} 0 {large} 0 {x2i:.1f} {y2i:.1f} Z" '
                f'fill="{color}" stroke="#0f172a" stroke-width="2"/>')

    donut_paths = ""
    cursor = 0.0
    for count, _, color in tier_data:
        pct = count / total_p
        if pct > 0:
            donut_paths += donut_path(cursor, cursor + pct, color)
        cursor += pct

    donut_svg = f"""
    <svg viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg" style="width:180px;height:180px">
      {donut_paths}
      <text x="90" y="86" text-anchor="middle" fill="#f1f5f9" font-size="14" font-weight="700">{total_p}</text>
      <text x="90" y="102" text-anchor="middle" fill="#94a3b8" font-size="9">products</text>
    </svg>"""

    price_tier_section = f"""
    <div class="tier-box">
      <div class="tier-donut">{donut_svg}</div>
      <div class="tier-legend">{tier_legend}</div>
    </div>"""

    # ── New drops section ─────────────────────────────────────────────────────
    drop_cards = ""
    for name, s in stores.items():
        if s["new_last_30d"] == 0:
            badge = '<span class="drop-badge inactive">No new drops</span>'
            titles_html = '<p class="no-drops">No new products in the last 30 days.</p>'
        else:
            badge = f'<span class="drop-badge active">{s["new_last_30d"]} new</span>'
            titles_html = "".join(
                f'<div class="drop-item">&#10022; {t}</div>'
                for t in s["new_titles"]
            )
        drop_cards += f"""
        <div class="drop-card">
          <div class="drop-header">
            <span class="drop-store">{name}</span>
            {badge}
          </div>
          {titles_html}
        </div>"""

    # ── Insights ──────────────────────────────────────────────────────────────
    insights = [
        ("Pricing Sweet Spot",
         "The mid-range $25–$50 segment dominates with 249 products (51% of market). "
         "Positioning here maximises discoverability without racing to the bottom."),
        ("Classic Candles Lead",
         "Classic Candle is the #1 product type across all stores. "
         "A strong core scented candle line is non-negotiable before expanding into EDP or body mist."),
        ("Gifting Is a Growth Lane",
         "Otherland's 3 new drops are all curated gift edits (Wedding, Full Bloom, Freshly Picked). "
         "Gift bundles command higher AOV and drive seasonal spikes."),
        ("Keap Is Asleep",
         "Keap Candles — the market's luxury leader at $77.88 avg — has had zero new drops in 30 days. "
         "A premium gap is open for differentiated launches above $60."),
        ("Car Fresheners Are Underrated",
         "Car fresheners appear in Homesick's top product types despite being a low-effort add-on. "
         "Adding a $12–$18 car freshener SKU broadens reach with minimal production cost."),
    ]
    insight_icons = ["01", "02", "03", "04", "05"]
    insights_html = ""
    for idx, (title, body) in enumerate(insights):
        insights_html += f"""
        <div class="insight-card">
          <div class="insight-num">{insight_icons[idx]}</div>
          <div class="insight-body">
            <div class="insight-title">{title}</div>
            <div class="insight-text">{body}</div>
          </div>
        </div>"""

    # ── Full HTML ─────────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Candle Market Intelligence — {date_fmt}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:       #0f172a;
    --surface:  #1e293b;
    --surface2: #273449;
    --border:   #334155;
    --text:     #f1f5f9;
    --muted:    #94a3b8;
    --accent:   #f97316;
    --accent2:  #3b82f6;
  }}

  body {{
    font-family: 'Inter', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    font-size: 14px;
    line-height: 1.6;
  }}

  /* ── Layout ── */
  .page {{ max-width: 1100px; margin: 0 auto; padding: 40px 24px 80px; }}

  /* ── Header ── */
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding: 40px 48px;
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border: 1px solid var(--border);
    border-radius: 16px;
    margin-bottom: 32px;
    position: relative;
    overflow: hidden;
  }}
  .header::before {{
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 240px; height: 240px;
    background: radial-gradient(circle, #f9731620 0%, transparent 70%);
    pointer-events: none;
  }}
  .header-left h1 {{
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.5px;
    margin-bottom: 6px;
  }}
  .header-left h1 span {{ color: var(--accent); }}
  .header-left p {{ color: var(--muted); font-size: 13px; }}
  .header-right {{
    text-align: right;
    flex-shrink: 0;
  }}
  .header-right .date {{
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 6px;
  }}
  .header-right .powered-by {{
    font-size: 11px;
    color: var(--border);
    background: var(--surface2);
    padding: 4px 10px;
    border-radius: 20px;
    border: 1px solid var(--border);
  }}

  /* ── Section titles ── */
  .section-title {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .section-title::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }}

  /* ── KPI grid ── */
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 16px;
    margin-bottom: 32px;
  }}
  .kpi-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 16px;
    text-align: center;
    transition: border-color .2s;
  }}
  .kpi-card:hover {{ border-color: var(--accent); }}
  .kpi-value {{
    font-size: 28px;
    font-weight: 800;
    color: var(--text);
    letter-spacing: -1px;
    line-height: 1;
    margin-bottom: 6px;
  }}
  .kpi-label {{
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }}

  /* ── Competitor table ── */
  .table-wrap {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 32px;
  }}
  .comp-table {{ width: 100%; border-collapse: collapse; }}
  .comp-table thead tr {{
    background: var(--surface2);
    border-bottom: 1px solid var(--border);
  }}
  .comp-table th {{
    padding: 12px 16px;
    text-align: left;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--muted);
    white-space: nowrap;
  }}
  .comp-table td {{
    padding: 14px 16px;
    border-bottom: 1px solid #1e2d42;
    vertical-align: middle;
  }}
  .comp-table tr:last-child td {{ border-bottom: none; }}
  .comp-table tr:hover td {{ background: #1a2844; }}
  .store-name {{ font-weight: 600; font-size: 13px; margin-bottom: 2px; }}
  .store-url {{ font-size: 11px; color: var(--accent2); text-decoration: none; }}
  .store-url:hover {{ text-decoration: underline; }}
  .num {{ font-size: 14px; font-weight: 600; color: var(--text); }}
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    white-space: nowrap;
  }}
  .tag {{
    display: inline-block;
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 10px;
    margin: 2px 2px 2px 0;
  }}
  .bar-wrap {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .bar {{
    height: 6px;
    border-radius: 3px;
    min-width: 4px;
    transition: width .3s;
  }}
  .bar-label {{ font-size: 12px; font-weight: 600; color: var(--text); }}

  /* ── Two-col row ── */
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 32px; }}
  .box {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
  }}

  /* ── Price tiers ── */
  .tier-box {{ display: flex; align-items: center; gap: 28px; }}
  .tier-donut {{ flex-shrink: 0; }}
  .tier-legend {{ display: flex; flex-direction: column; gap: 10px; }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--muted);
  }}
  .legend-item strong {{ color: var(--text); }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}

  /* ── New drops ── */
  .drops-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .drop-card {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }}
  .drop-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
  }}
  .drop-store {{ font-weight: 600; font-size: 13px; }}
  .drop-badge {{
    font-size: 11px;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 20px;
  }}
  .drop-badge.active {{
    background: #10b98122;
    color: #10b981;
    border: 1px solid #10b98166;
  }}
  .drop-badge.inactive {{
    background: #33415522;
    color: var(--muted);
    border: 1px solid var(--border);
  }}
  .drop-item {{
    font-size: 12px;
    color: var(--text);
    padding: 4px 0;
    border-bottom: 1px solid var(--border);
  }}
  .drop-item:last-child {{ border-bottom: none; }}
  .no-drops {{ font-size: 12px; color: var(--muted); font-style: italic; }}

  /* ── Insights ── */
  .insights-list {{ display: flex; flex-direction: column; gap: 14px; margin-bottom: 32px; }}
  .insight-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    display: flex;
    gap: 20px;
    align-items: flex-start;
    transition: border-color .2s;
  }}
  .insight-card:hover {{ border-color: var(--accent); }}
  .insight-num {{
    font-size: 11px;
    font-weight: 800;
    color: var(--accent);
    letter-spacing: 1px;
    background: #f9731615;
    border: 1px solid #f9731630;
    width: 36px; height: 36px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }}
  .insight-title {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 4px;
    color: var(--text);
  }}
  .insight-text {{ font-size: 13px; color: var(--muted); line-height: 1.6; }}

  /* ── Footer ── */
  .footer {{
    text-align: center;
    color: var(--border);
    font-size: 11px;
    margin-top: 48px;
    padding-top: 24px;
    border-top: 1px solid var(--border);
  }}

  /* ── Responsive ── */
  @media (max-width: 768px) {{
    .kpi-grid {{ grid-template-columns: repeat(3, 1fr); }}
    .two-col  {{ grid-template-columns: 1fr; }}
    .drops-grid {{ grid-template-columns: 1fr; }}
    .header {{ flex-direction: column; gap: 16px; }}
    .header-right {{ text-align: left; }}
  }}
</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div class="header">
    <div class="header-left">
      <h1>Candle Market <span>Intelligence</span></h1>
      <p>Automated competitor analysis across 5 Shopify stores — handmade &amp; small-batch candle niche</p>
    </div>
    <div class="header-right">
      <div class="date">{date_fmt}</div>
      <div class="powered-by">Powered by Groq · LLaMA 3.3 70B</div>
    </div>
  </div>

  <!-- KPIs -->
  <div class="section-title">Key Metrics</div>
  {kpi_cards}

  <!-- Competitor Table -->
  <div class="section-title">Competitor Comparison</div>
  <div class="table-wrap">
    {comp_table}
  </div>

  <!-- Price Tiers + New Drops -->
  <div class="two-col">
    <div class="box">
      <div class="section-title">Price Tier Distribution</div>
      {price_tier_section}
    </div>
    <div class="box">
      <div class="section-title">New Drop Activity (Last 30 Days)</div>
      <div class="drops-grid">
        {drop_cards}
      </div>
    </div>
  </div>

  <!-- Insights -->
  <div class="section-title">Actionable Insights</div>
  <div class="insights-list">
    {insights_html}
  </div>

  <!-- Footer -->
  <div class="footer">
    Generated by Candle Intel Agent &nbsp;·&nbsp; {date_fmt} &nbsp;·&nbsp;
    Data sourced from public Shopify product listings &nbsp;·&nbsp;
    AI analysis by Groq / LLaMA 3.3 70B
  </div>

</div>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*60}")
    print("  AGENT 4 -- HTML REPORT GENERATOR")
    print(f"{'='*60}\n")

    md, metrics = load_latest()
    print(f"  Loaded report for {metrics['date']}")
    print(f"  Building HTML...")

    html = build_html(md, metrics)

    out_path = Path("reports") / f"report_{metrics['date']}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Saved: {out_path}")
    print(f"\n  Open this file in your browser:")
    print(f"  {out_path.resolve()}\n")


if __name__ == "__main__":
    run()
