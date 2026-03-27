"""
Agent 4 — PDF Report Generator
Reads the metrics JSON + markdown report and produces a 5-page A4 PDF.
Uses ReportLab (built-in Helvetica, no external fonts needed).
"""

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle

from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

# ── Colours ───────────────────────────────────────────────────────────────────

NAVY   = HexColor("#0f172a")
BODY   = HexColor("#334155")
MUTED  = HexColor("#64748b")
SHADE  = HexColor("#f1f5f9")
WHITE  = colors.white
BLACK  = colors.black

# ── Styles ────────────────────────────────────────────────────────────────────

def make_styles():
    return {
        "title": ParagraphStyle(
            "title", fontName="Helvetica-Bold", fontSize=26, textColor=NAVY,
            leading=32, spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName="Helvetica", fontSize=12, textColor=MUTED,
            leading=16, spaceAfter=20,
        ),
        "section": ParagraphStyle(
            "section", fontName="Helvetica-Bold", fontSize=13, textColor=NAVY,
            leading=18, spaceBefore=18, spaceAfter=8,
        ),
        "intro": ParagraphStyle(
            "intro", fontName="Helvetica", fontSize=9, textColor=MUTED,
            leading=14, spaceAfter=10,
        ),
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=10, textColor=BODY,
            leading=15, spaceAfter=10,
        ),
        "label": ParagraphStyle(
            "label", fontName="Helvetica", fontSize=8, textColor=MUTED,
            leading=12, alignment=TA_CENTER,
        ),
        "stat_val": ParagraphStyle(
            "stat_val", fontName="Helvetica-Bold", fontSize=22, textColor=NAVY,
            leading=26, alignment=TA_CENTER,
        ),
        "action_num": ParagraphStyle(
            "action_num", fontName="Helvetica-Bold", fontSize=18, textColor=NAVY,
            leading=22, spaceAfter=4,
        ),
        "action_text": ParagraphStyle(
            "action_text", fontName="Helvetica", fontSize=10, textColor=BODY,
            leading=15, spaceAfter=18,
        ),
        "footer_note": ParagraphStyle(
            "footer_note", fontName="Helvetica", fontSize=8, textColor=MUTED,
            leading=12, alignment=TA_CENTER, spaceBefore=24,
        ),
    }


# ── Footer callback ───────────────────────────────────────────────────────────

def make_footer(date_str: str):
    def draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        text = f"Candle Intel  ·  Daily Intelligence Report  ·  {date_str}  ·  Page {doc.page}"
        canvas.drawCentredString(A4[0] / 2, 30, text)
        canvas.restoreState()
    return draw_footer


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_latest(reports_dir: str = "reports"):
    p = Path(reports_dir)
    json_files = sorted(p.glob("metrics_*.json"), reverse=True)
    md_files   = sorted(p.glob("report_*.md"),    reverse=True)
    if not json_files:
        raise FileNotFoundError("No metrics_*.json found in reports/")
    with open(json_files[0]) as f:
        metrics = json.load(f)
    md = ""
    if md_files:
        with open(md_files[0], encoding="utf-8") as f:
            md = f.read()
    return metrics, md


# ── Helpers ───────────────────────────────────────────────────────────────────

def segment(avg_price):
    if avg_price is None:
        return "—"
    if avg_price < 25:
        return "Budget"
    if avg_price < 50:
        return "Mid-Range"
    if avg_price < 100:
        return "Premium"
    return "Luxury"


def momentum_score(s: dict) -> int:
    new_drops   = s.get("new_last_30d", 0)
    total       = s.get("total_products", 0)
    mn          = s.get("min_price") or 0
    mx          = s.get("max_price") or 0
    price_range = max(mx - mn, 0)
    raw = (new_drops * 0.5) + (total / 50) + (price_range / 100)
    return min(10, round(raw))


def parse_snapshot(md: str) -> str:
    m = re.search(r"##\s*1\.\s*Market Snapshot\s*\n(.+?)(?=\n##|\Z)", md, re.DOTALL)
    if m:
        return m.group(1).strip()
    return "No AI snapshot available for this run."


def parse_actions(md: str, count: int = 3) -> list[str]:
    m = re.search(r"##\s*6\.\s*Actionable Insights[^\n]*\n(.+?)(?=\n##|\Z)", md, re.DOTALL)
    if not m:
        return ["No actions available." for _ in range(count)]
    block = m.group(1).strip()
    items = re.findall(r"^\d+\.\s+(.+)", block, re.MULTILINE)
    result = []
    for item in items[:count]:
        result.append(item.strip())
    while len(result) < count:
        result.append("No further actions available.")
    return result


def category_table_data(metrics: dict) -> list[tuple]:
    """Count how many stores each product type appears in."""
    store_counter: Counter = Counter()
    for s in metrics["stores"].values():
        for pt_name in s.get("top_product_types", []):
            store_counter[pt_name] += 1
    return store_counter.most_common(12)


def hr():
    return HRFlowable(width="100%", thickness=0.5, color=SHADE, spaceAfter=12, spaceBefore=4)


def section_heading(text, styles):
    return Paragraph(text, styles["section"])


def tbl_style(has_shading=True, rows=0) -> TableStyle:
    cmds = [
        ("BACKGROUND",  (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 9),
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 1), (-1, -1), 9),
        ("TEXTCOLOR",   (0, 1), (-1, -1), BODY),
        ("ROWBACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ALIGN",       (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("GRID",        (0, 0), (-1, -1), 0.25, HexColor("#e2e8f0")),
    ]
    if has_shading:
        for i in range(2, rows + 1, 2):
            cmds.append(("BACKGROUND", (0, i), (-1, i), SHADE))
    return TableStyle(cmds)


# ── Pages ─────────────────────────────────────────────────────────────────────

def page1_executive(metrics: dict, md: str, styles: dict) -> list:
    date_fmt = datetime.strptime(metrics["date"], "%Y-%m-%d").strftime("%B %d, %Y")
    stores   = metrics["stores"]
    total_new = sum(s["new_last_30d"] for s in stores.values())
    avg_prices = [s["avg_price"] for s in stores.values() if s.get("avg_price")]
    market_avg = f"${round(sum(avg_prices)/len(avg_prices), 2)}" if avg_prices else "—"

    story = [
        Paragraph("Candle Market Intelligence", styles["title"]),
        Paragraph(f"{date_fmt}  ·  Daily Brief", styles["subtitle"]),
        hr(),
        Spacer(1, 12),
    ]

    # 2×2 stat grid
    stat_data = [
        [
            Paragraph(str(metrics["total_products"]), styles["stat_val"]),
            Paragraph(str(metrics["total_stores"]), styles["stat_val"]),
        ],
        [
            Paragraph("Total Products Tracked", styles["label"]),
            Paragraph("Competitors Monitored", styles["label"]),
        ],
        [
            Paragraph(str(total_new), styles["stat_val"]),
            Paragraph(market_avg, styles["stat_val"]),
        ],
        [
            Paragraph("New Drops (Last 30 Days)", styles["label"]),
            Paragraph("Market Average Price", styles["label"]),
        ],
    ]
    stat_tbl = Table(stat_data, colWidths=[237, 237])
    stat_tbl.setStyle(TableStyle([
        ("BOX",         (0, 0), (0, 1), 0.5, HexColor("#e2e8f0")),
        ("BOX",         (1, 0), (1, 1), 0.5, HexColor("#e2e8f0")),
        ("BOX",         (0, 2), (0, 3), 0.5, HexColor("#e2e8f0")),
        ("BOX",         (1, 2), (1, 3), 0.5, HexColor("#e2e8f0")),
        ("BACKGROUND",  (0, 0), (-1, -1), SHADE),
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [stat_tbl, Spacer(1, 24)]

    # Key Insight
    story += [
        section_heading("Today's Key Insight", styles),
        Paragraph(parse_snapshot(md), styles["body"]),
        PageBreak(),
    ]
    return story


def page2_momentum(metrics: dict, styles: dict) -> list:
    stores = metrics["stores"]
    story = [
        section_heading("Market Momentum Scores", styles),
        Paragraph(
            "Momentum is calculated from new product activity, pricing range, and catalogue volume. Scored 1–10.",
            styles["intro"],
        ),
        Spacer(1, 8),
    ]

    header = ["Brand", "Products", "New Drops (30d)", "Price Range", "Momentum"]
    rows = [header]
    for name, s in stores.items():
        mn = s.get("min_price") or 0
        mx = s.get("max_price") or 0
        price_range = f"${mn} – ${mx}" if mn or mx else "—"
        score = momentum_score(s)
        rows.append([
            name,
            str(s["total_products"]),
            str(s["new_last_30d"]),
            price_range,
            str(score) + " / 10",
        ])

    tbl = Table(rows, colWidths=[160, 70, 90, 110, 70])
    tbl.setStyle(tbl_style(has_shading=True, rows=len(rows) - 1))
    story += [tbl, PageBreak()]
    return story


def page3_competitor(metrics: dict, styles: dict) -> list:
    stores = metrics["stores"]
    story = [
        section_heading("Competitor Comparison", styles),
        Spacer(1, 8),
    ]

    header = ["Store", "Products", "Avg Price", "Price Range", "Segment", "Top Categories"]
    rows = [header]
    for name, s in stores.items():
        mn = s.get("min_price") or 0
        mx = s.get("max_price") or 0
        avg = f"${s['avg_price']}" if s.get("avg_price") else "—"
        price_range = f"${mn} – ${mx}" if mn or mx else "—"
        cats = ", ".join(s.get("top_product_types", [])[:3]) or "—"
        rows.append([name, str(s["total_products"]), avg, price_range, segment(s.get("avg_price")), cats])

    tbl = Table(rows, colWidths=[110, 55, 60, 90, 65, 115])
    tbl.setStyle(tbl_style(has_shading=True, rows=len(rows) - 1))
    story += [tbl, PageBreak()]
    return story


def page4_launches_categories(metrics: dict, styles: dict) -> list:
    stores = metrics["stores"]
    story = [section_heading("New Launches — Last 30 Days", styles)]

    any_launches = any(s["new_last_30d"] > 0 for s in stores.values())
    if not any_launches:
        story.append(Paragraph("No new products detected in this period.", styles["body"]))
    else:
        for name, s in stores.items():
            if s["new_last_30d"] == 0:
                continue
            story.append(Paragraph(f"<b>{name}</b>", styles["body"]))
            for title in s.get("new_titles", []):
                price = s.get("avg_price")
                price_str = f"  —  ~${price}" if price else ""
                story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;• {title}{price_str}", styles["body"]))
            story.append(Spacer(1, 6))

    story += [hr(), section_heading("Category Intelligence", styles)]

    cat_counts = category_table_data(metrics)
    if cat_counts:
        cat_most = cat_counts[0][0]
        cat_least = cat_counts[-1][0] if len(cat_counts) > 1 else "—"
        header = ["Category", "Appearances Across Brands"]
        rows = [header]
        for cat, count in cat_counts:
            rows.append([cat, str(count)])
        tbl = Table(rows, colWidths=[300, 195])
        tbl.setStyle(tbl_style(has_shading=True, rows=len(rows) - 1))
        story += [
            tbl,
            Spacer(1, 14),
            Paragraph(
                f"Most represented: <b>{cat_most}</b>  ·  "
                f"Least represented (potential gap): <b>{cat_least}</b>",
                styles["body"],
            ),
        ]
    story.append(PageBreak())
    return story


def page5_watch(md: str, styles: dict) -> list:
    actions = parse_actions(md, count=3)
    story = [
        section_heading("3 Areas to Watch Today", styles),
        Paragraph(
            "The following patterns were flagged by AI analysis of today's market data.",
            styles["intro"],
        ),
        Spacer(1, 16),
    ]

    for i, action in enumerate(actions, 1):
        story += [
            Paragraph(str(i), styles["action_num"]),
            Paragraph(action, styles["action_text"]),
        ]
        if i < 3:
            story.append(hr())

    story += [
        Spacer(1, 40),
        Paragraph(
            "Candle Intel surfaces market intelligence. Strategic decisions remain with your team.",
            styles["footer_note"],
        ),
    ]
    return story


# ── Build PDF ─────────────────────────────────────────────────────────────────

def build_pdf(metrics: dict, md: str) -> str:
    date_str = metrics["date"]
    date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    out_path = str(Path("reports") / f"report_{date_str}.pdf")

    footer_fn = make_footer(date_fmt)
    doc = BaseDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50,
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="main",
    )
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=footer_fn)])

    styles = make_styles()
    story = []
    story += page1_executive(metrics, md, styles)
    story += page2_momentum(metrics, styles)
    story += page3_competitor(metrics, styles)
    story += page4_launches_categories(metrics, styles)
    story += page5_watch(md, styles)

    doc.build(story)
    return out_path


# ── Entry point ───────────────────────────────────────────────────────────────

def run() -> str:
    print(f"\n{'='*60}")
    print("  AGENT 4 -- PDF REPORT GENERATOR")
    print(f"{'='*60}\n")

    metrics, md = load_latest()
    print(f"  Loaded metrics for {metrics['date']}")
    print(f"  Building PDF...")

    pdf_path = build_pdf(metrics, md)
    abs_path = str(Path(pdf_path).resolve())

    print(f"  Saved: {pdf_path}")
    print(f"\n  PDF path: {abs_path}\n")
    return pdf_path


if __name__ == "__main__":
    run()
