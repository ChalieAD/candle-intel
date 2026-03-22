# Candle Intel — AI-Powered Competitor Intelligence System

> Automatically tracks competitor products, prices, and new launches across the handmade candle niche — every day, with zero manual input.

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)
![Groq](https://img.shields.io/badge/AI-Groq%20%2F%20LLaMA%203.3%2070B-orange?style=flat-square)
![GitHub Actions](https://img.shields.io/badge/Automation-GitHub%20Actions-2088FF?style=flat-square&logo=github-actions)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## What This Does

Candle Intel is a fully automated multi-agent pipeline that:

1. **Discovers** 5 real competitor Shopify stores in the handmade candle niche
2. **Scrapes** live product data — titles, prices, variants, new drops — from all 5 stores
3. **Analyses** 490+ products using an LLM (Groq / LLaMA 3.3 70B) to surface pricing patterns, market gaps, and trends
4. **Generates** a beautiful, self-contained HTML report with charts, competitor tables, and KPI cards
5. **Emails** the report to your inbox every morning at 7am — automatically, via GitHub Actions

No dashboards to check. No manual work. Just open your email.

---

## Live Output

The system produces a dark-themed HTML intelligence report containing:

| Section | Content |
|---|---|
| KPI Cards | Total products tracked, new drops, market avg price, most active store |
| Competitor Table | Avg / min / max price, new drop activity bar, segment badge, top categories |
| Price Tier Donut | SVG chart — Budget / Mid-Range / Premium / Luxury breakdown |
| New Drop Grid | Every product launched in the last 30 days, per store |
| AI Insights | 5 numbered, data-backed recommendations from the LLM |

---

## System Architecture

```
run.py (orchestrator)
│
├── agent1_discover.py   — Load niche config + competitor list
├── agent2_collect.py    — Hit Shopify /products.json on all stores
├── agent3_analyse.py    — Compute metrics, send to Groq LLM, get narrative
├── agent4_report.py     — Build self-contained HTML report (pure Python, no deps)
└── agent5_email.py      — Send report via Gmail SMTP
```

**Data flow:**

```
competitors.json
      │
      ▼
[Agent 1] niche + URLs
      │
      ▼
[Agent 2] 490 products → data/products_YYYY-MM-DD.json
      │
      ▼
[Agent 3] metrics + LLM narrative → reports/report_YYYY-MM-DD.md
      │
      ▼
[Agent 4] HTML report → reports/report_YYYY-MM-DD.html
      │
      ▼
[Agent 5] email → inbox
```

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11 |
| Data collection | `urllib` (no scraping library needed — Shopify's public JSON API) |
| Data processing | `pandas` |
| AI analysis | [Groq API](https://console.groq.com) — LLaMA 3.3 70B Versatile |
| Report generation | Pure Python HTML/SVG (zero frontend dependencies) |
| Email delivery | Gmail SMTP via `smtplib` |
| Automation | GitHub Actions (cron schedule) |
| Config | `python-dotenv` |

---

## Competitors Tracked

| Store | URL | Segment | Products |
|---|---|---|---|
| P.F. Candle Co. | pfcandleco.com | Mid-Range | 76 |
| Keap Candles | keapcandles.com | Luxury | 28 |
| Homesick | homesick.com | Budget | 234 |
| Otherland | otherland.com | Mid-Range | 55 |
| Boy Smells | boysmells.com | Premium | 97 |

> To track a different niche, edit `competitors.json` — any Shopify store works out of the box.

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/candle-intel.git
cd candle-intel
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
GROQ_API_KEY=your_groq_api_key        # free at console.groq.com
GMAIL_SENDER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx  # Gmail App Password (not your login password)
EMAIL_RECIPIENT=you@gmail.com
```

### 3. Run

```bash
# Full pipeline — scrape + analyse + report + email
python run.py

# Skip re-scraping, just re-analyse existing data
python run.py --skip-collect

# Run without sending email
python run.py --no-email
```

Reports are saved to `reports/report_YYYY-MM-DD.html`.

---

## Automated Daily Runs (GitHub Actions)

The workflow at `.github/workflows/daily_report.yml` runs every day at **07:00 UTC**.

### Setup

1. Push this repo to GitHub
2. Go to **Settings → Secrets and variables → Actions**
3. Add these four secrets:

| Secret | Value |
|---|---|
| `GROQ_API_KEY` | Your Groq API key |
| `GMAIL_SENDER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Your Gmail App Password |
| `EMAIL_RECIPIENT` | Where to send the report |

4. Go to **Actions → Daily Candle Intel Report → Run workflow** to trigger a test run

After that, reports arrive in your inbox every morning — no machine needs to be on.
Reports are also stored as GitHub Actions artifacts for 30 days.

### Getting a Gmail App Password

1. Enable 2-Step Verification on your Google account
2. Go to `myaccount.google.com` → Security → App Passwords
3. Generate a password for "Mail"
4. Use the 16-character code as `GMAIL_APP_PASSWORD`

---

## Project Structure

```
candle-intel/
├── agent1_discover.py          # Niche & competitor loader
├── agent2_collect.py           # Shopify product data collector
├── agent3_analyse.py           # Metrics + Groq LLM analysis
├── agent4_report.py            # HTML report generator
├── agent5_email.py             # Gmail delivery
├── run.py                      # Pipeline orchestrator
├── competitors.json            # Niche config — edit to change targets
├── requirements.txt
├── .env.example                # Environment variable template
├── .gitignore                  # .env and data/ excluded
└── .github/
    └── workflows/
        └── daily_report.yml    # GitHub Actions cron job
```

---

## Extending This System

This pipeline is designed to be niche-agnostic. Swap in any Shopify store URLs and it works immediately. Some ideas:

- **Different niches** — skincare, supplements, streetwear, pet accessories
- **More stores** — add as many URLs to `competitors.json` as you want
- **Slack delivery** — replace Agent 5 with a Slack webhook
- **Price alerts** — trigger an email only when a competitor drops prices > 20%
- **Historical tracking** — compare today's data against last week's JSON

---

## About

Built as a portfolio project demonstrating:

- **Multi-agent AI architecture** — discrete agents with single responsibilities
- **Real-world data collection** — live product data from production Shopify stores
- **LLM integration** — structured metrics → natural language insights via Groq
- **End-to-end automation** — from raw data to inbox with no human in the loop
- **Production deployment** — GitHub Actions cron, secrets management, artifact storage

---

*Built with Python · Groq · LLaMA 3.3 70B · GitHub Actions*
