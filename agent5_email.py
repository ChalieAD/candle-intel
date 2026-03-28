"""
Agent 5 — Email Delivery + Supabase
Sends a clean minimal HTML email with the PDF report attached,
then writes a run summary to Supabase agent_outputs.
"""

import json
import os
import re
import smtplib
from datetime import date, datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_latest_pdf(reports_dir: str = "reports") -> str:
    files = sorted(Path(reports_dir).glob("report_*.pdf"), reverse=True)
    if not files:
        raise FileNotFoundError("No PDF report found in reports/. Run agent4_report.py first.")
    return str(files[0])


def load_latest_metrics(reports_dir: str = "reports") -> dict:
    files = sorted(Path(reports_dir).glob("metrics_*.json"), reverse=True)
    if not files:
        return {}
    with open(files[0]) as f:
        return json.load(f)


def load_latest_md(reports_dir: str = "reports") -> str:
    files = sorted(Path(reports_dir).glob("report_*.md"), reverse=True)
    if not files:
        return ""
    with open(files[0], encoding="utf-8") as f:
        return f.read()


# ── Email content ─────────────────────────────────────────────────────────────

def extract_notable_movement(md: str) -> str:
    """Pull the first sentence from the New Drop Activity section."""
    m = re.search(r"##\s*3\.\s*New Drop Activity\s*\n(.+?)(?=\n##|\Z)", md, re.DOTALL)
    if not m:
        return "New product activity detected across tracked competitors."
    lines = [l.strip() for l in m.group(1).strip().splitlines() if l.strip() and not l.startswith("-")]
    return lines[0] if lines else "New product activity detected across tracked competitors."


def _new_drops_sentence(stores: dict) -> str:
    launchers = sorted(
        [(name, s.get("new_last_30d", 0)) for name, s in stores.items()
         if s.get("new_last_30d", 0) > 0],
        key=lambda x: x[1], reverse=True,
    )
    if not launchers:
        return "No new products detected across tracked competitors in the last 30 days."
    parts = [f"{name} ({count})" for name, count in launchers]
    if len(parts) == 1:
        return f"{parts[0]} launched new products in the last 30 days."
    return f"{', '.join(parts[:-1])} and {parts[-1]} launched new products in the last 30 days."


def build_email_html(metrics: dict, md: str) -> str:
    stores    = metrics.get("stores", {})
    date_str  = metrics.get("date", date.today().isoformat())
    date_fmt  = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")

    avg_prices  = [s["avg_price"] for s in stores.values() if s.get("avg_price")]
    market_avg  = round(sum(avg_prices) / len(avg_prices), 2) if avg_prices else 0

    most_active_name, most_active_drops = "", 0
    if stores:
        ma = max(stores.items(), key=lambda x: x[1].get("new_last_30d", 0))
        most_active_name  = ma[0]
        most_active_drops = ma[1].get("new_last_30d", 0)

    new_drops_sentence = _new_drops_sentence(stores)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Candle Intel · {date_fmt}</title>
</head>
<body style="margin:0;padding:0;background:#ffffff;font-family:system-ui,-apple-system,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;">
  <tr>
    <td align="center" style="padding:40px 20px;">
      <table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="padding-bottom:24px;border-bottom:1px solid #e2e8f0;">
            <p style="margin:0;font-size:12px;color:#94a3b8;letter-spacing:0.05em;">
              Candle Intel &nbsp;·&nbsp; {date_fmt}
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding-top:28px;padding-bottom:28px;">
            <p style="margin:0 0 20px 0;font-size:18px;font-weight:700;color:#0f172a;line-height:1.4;">
              Here's what moved in your market today.
            </p>

            <ul style="margin:0 0 24px 0;padding-left:20px;color:#334155;font-size:14px;line-height:1.8;">
              <li style="margin-bottom:6px;">
                <strong>{most_active_name}</strong> was the most active brand
                with <strong>{most_active_drops} new drop{"s" if most_active_drops != 1 else ""}</strong> in the last 30 days.
              </li>
              <li style="margin-bottom:6px;">
                The market average price is currently <strong>${market_avg}</strong> across all tracked competitors.
              </li>
              <li style="margin-bottom:6px;">
                {new_drops_sentence}
              </li>
            </ul>

            <p style="margin:0 0 20px 0;font-size:14px;color:#334155;line-height:1.6;">
              Today's full report covers competitor pricing, new launches, and 3 areas worth watching.
            </p>

            <p style="margin:0;font-size:14px;color:#0f172a;font-weight:700;">
              Report attached.
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding-top:24px;border-top:1px solid #e2e8f0;">
            <p style="margin:0;font-size:11px;color:#94a3b8;">
              Candle Intel &nbsp;·&nbsp; Automated competitor intelligence &nbsp;·&nbsp; {date_fmt}
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def build_plain_text(date_fmt: str) -> str:
    return f"Candle Intel · {date_fmt}\n\nHere's what moved in your market today.\nFull report attached as PDF.\n"


# ── Send ──────────────────────────────────────────────────────────────────────

def send(pdf_path: str, html: str, plain: str, sender: str, app_password: str, recipient: str) -> None:
    date_fmt = datetime.now().strftime("%B %d, %Y")
    subject  = f"Candle Intel — {date_fmt}"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = f"Candle Intel <{sender}>"
    msg["To"]      = recipient

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain, "plain"))
    alt.attach(MIMEText(html,  "html"))
    msg.attach(alt)

    # Attach PDF
    with open(pdf_path, "rb") as f:
        pdf_part = MIMEBase("application", "pdf")
        pdf_part.set_payload(f.read())
    encoders.encode_base64(pdf_part)
    pdf_part.add_header("Content-Disposition", "attachment", filename=Path(pdf_path).name)
    msg.attach(pdf_part)

    print(f"  Connecting to smtp.gmail.com:587...")
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, app_password)
        server.sendmail(sender, recipient, msg.as_string())

    print(f"  Sent to {recipient}")


# ── Supabase ──────────────────────────────────────────────────────────────────

def build_supabase_summary(metrics: dict) -> dict:
    stores    = metrics.get("stores", {})
    total_new = sum(s.get("new_last_30d", 0) for s in stores.values())
    avg_prices = [s["avg_price"] for s in stores.values() if s.get("avg_price")]
    market_avg = round(sum(avg_prices) / len(avg_prices), 2) if avg_prices else 0
    most_active = max(stores.items(), key=lambda x: x[1].get("new_last_30d", 0), default=("", {}))[0]

    return {
        "total_products":    metrics.get("total_products", 0),
        "total_stores":      metrics.get("total_stores", 0),
        "total_new_drops":   total_new,
        "market_avg_price":  market_avg,
        "most_active_store": most_active,
        "price_tiers":       metrics.get("price_tiers", {}),
        "store_summaries": {
            name: {
                "total_products": s.get("total_products", 0),
                "new_last_30d":   s.get("new_last_30d", 0),
                "avg_price":      s.get("avg_price"),
            }
            for name, s in stores.items()
        },
    }


def write_to_supabase(summary: dict) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("  [Supabase] SUPABASE_URL/SUPABASE_KEY not set — skipping")
        return

    resp = requests.post(
        f"{url}/rest/v1/agent_outputs",
        headers={
            "apikey":        key,
            "Authorization": f"Bearer {key}",
            "Content-Type":  "application/json",
            "Prefer":        "return=minimal",
        },
        json={
            "agent_name": "candle-intel",
            "run_date":   date.today().isoformat(),
            "summary":    summary,
        },
        timeout=10,
    )
    resp.raise_for_status()
    print("  [Supabase] Run summary written to agent_outputs")


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*60}")
    print("  AGENT 5 -- EMAIL DELIVERY")
    print(f"{'='*60}\n")

    sender       = os.environ.get("GMAIL_SENDER")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient    = os.environ.get("EMAIL_RECIPIENT")

    missing = [k for k, v in {
        "GMAIL_SENDER":       sender,
        "GMAIL_APP_PASSWORD": app_password,
        "EMAIL_RECIPIENT":    recipient,
    }.items() if not v]
    if missing:
        raise EnvironmentError(f"Missing env vars: {', '.join(missing)}")

    metrics  = load_latest_metrics()
    md       = load_latest_md()
    pdf_path = load_latest_pdf()
    html     = build_email_html(metrics, md)
    plain    = build_plain_text(datetime.now().strftime("%B %d, %Y"))

    print(f"  [1/2] Sending email with PDF: {pdf_path}")
    send(pdf_path, html, plain, sender, app_password, recipient)
    print("  [OK] Email delivered.")

    print(f"\n  [2/2] Writing to Supabase...")
    try:
        summary = build_supabase_summary(metrics)
        write_to_supabase(summary)
    except Exception as e:
        print(f"  [ERROR] Supabase write failed: {e}")
        raise
    print()


if __name__ == "__main__":
    run()
