# Gig Income Ledger

A local income reconstruction and analytics tool for Indian gig workers.
Upload bank statement PDFs from any bank — the system parses every transaction,
identifies gig platform payouts (Swiggy, Zomato, Uber, Ola, Rapido), computes
monthly income analytics, and renders a results page in the browser.

**This is not a credit-scoring or lending product. It does not give financial
advice, generate eligibility scores, or recommend loans. It only describes past
income facts derived from your own statements.**

---

## Why it exists

Gig workers in India earn from multiple platforms simultaneously. Their income
appears scattered across dozens of UPI credit lines in a bank statement with no
single consolidated view. Getting a clear picture of earnings — how much came
from which platform, whether income is growing or volatile, how long the longest
dry spell was — requires manually going through hundreds of rows.

This tool automates that reconstruction without sending your raw financial data
to any third-party service. The only external call is an optional Gemini request
for prose rephrasing — it receives only the anonymised summary text, never raw
transaction data or account details. When hosted, your PDFs are processed
server-side and discarded immediately after parsing; nothing is stored.

---

## What it is not

- Not a credit score generator
- Not a lending eligibility tool
- Not a tax filing tool
- Not a multi-user or cloud service
- Not compatible with scanned/image PDFs (text-based PDFs only)

---

## Tech stack

| Layer | Technology |
|---|---|
| PDF parsing | pdfplumber + Gemini 2.0 Flash (extraction only) |
| Classification | Rule-based only — no LLM |
| Storage | SQLite via Python stdlib `sqlite3` |
| Analytics | Pure Python — OLS trend, SD volatility, no scipy |
| Summary prose | Gemini 2.0 Flash (optional, validated output only) |
| Frontend | Vanilla JS + inline SVG — no framework, no CDN, no build step |
| Server | Python stdlib `http.server` — no Flask, no FastAPI |

---

## Setup

### 1. Install dependencies

```
pip install -r requirements.txt
```

### 2. Set your Gemini API key

Copy `.env.example` to `.env` and add your key:

```
GEMINI_API_KEY=your_key_here
```

Get a free key at https://aistudio.google.com/app/apikey

The key is used for two things:
- **Parsing** — Gemini reads the raw PDF text and extracts structured transaction rows (any bank format)
- **Summary** — Gemini rephrases the income summary into plain language

Both fall back gracefully if the key is missing or the quota is exhausted.

### 3. Start the server

```
python -m income_ledger.server
```

Opens `http://127.0.0.1:8765/` in your browser automatically.

---

## Demo bank statements

Download sample bank statements to try the app:

**[Demo bank statements (Google Drive)](https://drive.google.com/drive/folders/1ZklSbxMXyOQh-EHk9qcJBcisBUzdINzP?usp=sharing)**

These are synthetic statements containing realistic gig platform transactions (Swiggy, Zomato, Uber, Ola) — no real financial data.

---

## How to use

1. Drag and drop one or more bank statement PDFs onto the upload zone, or click **Browse files**
2. Each file is parsed immediately — watch the status pill update per file
3. If any transaction is ambiguous (confidence < 70%), it appears in the **Needs confirmation** queue showing the exact bank narration — tag it with a platform or mark it as "not income"
4. Once all files are done and the queue is clear, the results page appears automatically
5. Click **Upload again** to start a fresh session

---

## How it works — module by module

### `income_ledger/parser.py` — PDF → raw transactions

Three strategies tried in order:

**1. LLM parser (primary)**
Extracts all text from the PDF via pdfplumber, sends it to Gemini with a strict
prompt asking for a JSON array of `{date, description, debit, credit}` rows.
Every field in the response is validated before use — invalid rows are skipped,
not rejected wholesale. Works on any bank format.

**2. Smart table parser (fallback)**
Scans the PDF table's header row for keywords (`date`, `narration`, `debit`,
`credit`, `withdrawal`, `deposit`) to auto-detect column positions. Understands
multiple date formats: `DD/MM/YYYY`, `DD-MM-YYYY`, `DD-Mon-YYYY` (HDFC style),
`YYYY-MM-DD`. Falls back to SBI column order if no header is found.

**3. Line scanner (last resort)**
Reads raw text line by line. Any line starting with a recognisable date and
containing at least one number is treated as a transaction. Credit/debit is
inferred from keywords (`CR`, `DR`, `DEPOSIT`, `WITHDRAWAL`) on the line.

If the PDF has no extractable text at all (scanned image), a `ScannedPdfError`
is raised immediately — OCR is out of scope.

---

### `income_ledger/classifier.py` — raw transactions → income events

Rule-based only. No LLM is used here.

Platform keyword patterns checked against the transaction description:

| Platform | Keywords |
|---|---|
| Swiggy | `SWIGGY`, `SWGY` |
| Zomato | `ZOMATO`, `ZMT` |
| Uber | `UBER` |
| Ola | `OLA` |
| Rapido | `RAPIDO` |

Refund markers: `REFUND`, `REVERSAL`, `RFND`, `RVSL`

Classification order (first match wins):

1. Any refund marker present → `REVERSAL` (regardless of platform)
2. Debit + platform + refund marker → `REVERSAL` with platform tag kept (so it subtracts from that platform's net income correctly)
3. Debit + platform + no refund marker → `UNMATCHED` (could be a fee, not assumed income)
4. Platform seen only once in the whole statement → `AMBIGUOUS` (one data point can't confirm a payout cadence)
5. Platform seen multiple times, no refund marker → `EXACT`
6. No platform match → `UNMATCHED`

`AMBIGUOUS` and `UNMATCHED` events are flagged for user confirmation and never silently included in totals.

---

### `income_ledger/ledger.py` — events → SQLite → monthly summaries

Persists classified events to a SQLite database (one throwaway db per upload
session, deleted when the session ends).

Net income per platform per month is computed as:

```
net = sum(payout credits) − sum(reversal amounts)
```

`platform = "unknown"` is excluded entirely from monthly summaries.
Debit-side reversals (bank clawbacks) reduce the platform's net income.

---

### `income_ledger/analytics.py` — monthly summaries → analytics report

| Metric | How computed |
|---|---|
| Average monthly income | Total net income ÷ number of months |
| Platform contribution % | Each platform's net ÷ total net × 100 |
| Trend | OLS linear regression on monthly totals. Needs ≥ 6 months. GROWING/DECLINING only if 95% CI excludes zero. Below 6 months → `insufficient_data`. |
| Volatility (absolute) | Standard deviation of monthly totals in rupees |
| Coefficient of variation | SD ÷ mean. Only computed when mean ≥ Rs 2,000 — below that the ratio is mathematically unstable. |
| Longest income gap | Largest number of days between consecutive payout dates |

Volatility is reported both per-platform and combined. A combined figure alone
would hide cases where one platform drops while another compensates.

---

### `income_ledger/summary.py` — analytics report → plain-language paragraph

Two paths, always in this order:

1. **Template** — all numbers are injected via f-strings directly from the
   analytics report. This is the ground truth output.

2. **Gemini rephrasing** — the template text is sent to Gemini and asked to
   be rewritten in friendlier language. Before the output is accepted, two
   strict checks run:
   - Every numeric token in Gemini's response is extracted and checked against
     the analytics report within a rounding tolerance. Any invented or altered
     number → rejected.
   - Output is scanned for forbidden phrases: `loan`, `credit score`, `EMI`,
     `eligible for`, `interest rate`, `we recommend`, `you should borrow`.
     Any match → rejected.

   If either check fails, the template is used instead. No unvalidated text
   ever reaches the user.

---

### `income_ledger/pipeline.py` — wires everything together

```
PDF path
  │
  ▼
parse_sbi_statement()        parser.py      → list[RawTransaction]
  │
  ▼
classify_statement()         classifier.py  → list[IncomeEvent]
  │
  ▼
Ledger.add_events()          ledger.py      → stored in SQLite
Ledger.recompute_monthly_summaries()        → list[MonthlySummary]
  │
  ▼
generate_analytics_report()  analytics.py   → AnalyticsReport
  │
  ▼
generate_summary()           summary.py     → SummaryResult
  │
  ▼
render_results_fragment()    render_report.py → list[dict] (JSON)
```

---

### `income_ledger/server.py` — HTTP server + browser frontend

**Python side**

- `GET /` — serves the single-page app
- `POST /upload` — receives one PDF, runs the full pipeline, returns JSON events

Uses Python's stdlib `http.server` with a custom multipart/form-data parser
(the `cgi` module was removed in Python 3.13).

**JavaScript side (embedded in the HTML)**

- Drag-and-drop or browse to add multiple PDFs
- Each file is sent to `POST /upload` independently and in parallel
- Per-file status pills: `Uploading → Parsing → Done / Error`
- Events from all files are merged into one combined ledger
- Deduplication by `date|amount|platform` prevents double-counting the same
  payout if it appears in both a bank statement and a platform export
- Events with confidence < 0.7 go to a confirmation queue showing the exact
  raw bank narration — user tags with a platform or marks "not income"
- Aggregation filters: only `payout` credits and `reversal` subtractions enter
  the totals — ATM withdrawals, bills, rent are excluded
- Results rendered client-side: KPI cards, SVG income chart, platform breakdown
  table, recent events table
- "Upload again" resets all state without a page reload

---

## Data flow diagram

```
┌─────────────────────────────────────────────────────────┐
│                      Browser                            │
│                                                         │
│  User drops PDF  ──►  POST /upload (multipart/form)     │
│                                                         │
│  ◄──  JSON list of IncomeEvent dicts                    │
│                                                         │
│  Merge + dedup + confidence split                       │
│  ├── confidence ≥ 0.7  →  allEvents (confirmed)         │
│  └── confidence < 0.7  →  pendingConf (confirmation UI) │
│                                                         │
│  User resolves queue  →  Generate Report                │
│                                                         │
│  Client-side aggregation  →  Results page               │
└─────────────────────────────────────────────────────────┘
                        │  POST /upload
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  Python Server                          │
│                                                         │
│  PDF bytes saved to temp dir                            │
│       │                                                 │
│       ▼                                                 │
│  parser.py                                              │
│  ├── pdfplumber extracts raw text                       │
│  ├── Gemini parses text → JSON rows  (primary)          │
│  ├── Smart table parser             (fallback)          │
│  └── Line-by-line scanner           (last resort)       │
│       │                                                 │
│       ▼  list[RawTransaction]                           │
│  classifier.py                                          │
│  └── Rule-based platform + reversal detection           │
│       │                                                 │
│       ▼  list[IncomeEvent]                              │
│  ledger.py  (SQLite, temp db)                           │
│  └── net income per platform per month                  │
│       │                                                 │
│       ▼  list[MonthlySummary]                           │
│  analytics.py                                           │
│  └── avg, trend (OLS), volatility, gaps                 │
│       │                                                 │
│       ▼  AnalyticsReport                                │
│  summary.py                                             │
│  └── template + optional Gemini rephrasing              │
│       │                                                 │
│       ▼  SummaryResult                                  │
│  render_report.py                                       │
│  └── serialise to JSON event list                       │
│       │                                                 │
│       ▼  HTTP 200 JSON                                  │
└─────────────────────────────────────────────────────────┘
```

---

## Confidence levels

| Value | Meaning | Goes to |
|---|---|---|
| 0.95 | EXACT — platform seen multiple times, clean payout | Confirmed automatically |
| 0.90 | REVERSAL — refund/clawback, direction clear | Confirmed, subtracted from net |
| 0.80 | ADJUSTMENT — debit side, platform unknown | Confirmed (excluded from income totals) |
| 0.55 | AMBIGUOUS — platform seen only once | Confirmation queue |
| 0.40 | UNMATCHED — no platform pattern found | Confirmation queue |

---

## Running tests

```
python -m pytest tests/ -v
```

76 tests covering schemas, parser, classifier, ledger, analytics, summary,
render, pipeline, and server multipart parsing.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | No | — | Enables LLM parsing and summary rephrasing |
| `SERVER_PORT` | No | `8765` | Port the local server listens on |
| `SERVER_OPEN_BROWSER` | No | `true` | Set to `false` to not open browser on start |

---

## Important constraints

- **Single user** — no authentication, no multi-tenant support
- **Text-based PDFs only** — scanned/image PDFs are rejected with a clear error
- **No persistent storage** — uploaded PDFs are processed in a temporary directory and deleted immediately; nothing is written to disk after the response is sent
- **Gemini calls never receive raw transaction data** — the parser sends raw PDF text; the summary call sends only the anonymised template text with no names or account numbers
- **No persistent storage** — each upload session uses a throwaway SQLite database deleted when the session ends
