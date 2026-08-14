# Tender Finder — concurrent download → range-check → Lark pipeline

Replaces the slow, manual SOP with a always-on pipeline. Three worker stages run
concurrently, connected only by queues, so downloading never waits for checking,
and checking never waits for uploading.

```
 site(s) ──▶ [Downloader] ──▶ Queue A ──▶ [Range Checker] ──pass──▶ Queue B
   (Worker 1, one thread          │              (Worker 2)              │
    per site)                     │                                     │
                               reject                              [Uploader]  ──fail──▶ Queue Retry
                                  ▼                                (Worker 3)               │
                             rejected/                                 │                    ▼
                                                                  completed/          [Retry Worker]
                                                                                            │
                                                                                            ▼
                                                                                       completed/
```

## Quick start (runs offline, no setup)

```bash
python3 main.py        # Ctrl-C to stop
```

Out of the box a built-in **mock site** fabricates tenders so you can watch the
whole pipeline work. Passed tenders land in `completed/`, rejected ones in
`rejected/` (each with a `.txt` explaining why), and everything is logged to
`logs/app.log`. No dependencies are required for the mock run — features degrade
gracefully if `pdfplumber`/`requests`/`playwright` aren't installed.

To run for real:

```bash
pip install -r requirements.txt
playwright install chromium        # only needed for real site scraping
cp .env.example .env               # then edit .env
set -a; source .env; set +a
python3 main.py
```

## What you configure — everything lives in `config.py`

| What | Where | Notes |
|------|-------|-------|
| Which sites to scrape | `SITES` | one `SiteConfig` per portal; toggle with `enabled` / env vars |
| Value range | `RANGE_RULES.min_value` / `max_value` | rupees; `None` disables a bound |
| Date window | `RANGE_RULES.closing_from` / `closing_to` | plus optional publish-date window |
| Lark delivery | `LARK.mode` | `noop` \| `webhook` \| `bot` |
| Retry policy | `PIPELINE.retry_delay_seconds` / `max_upload_attempts` | |

Secrets (passwords, Lark app id/secret) come from environment variables, never
the source — see `.env.example`.

## The four workers

- **`workers/downloader.py`** — one thread per enabled site. Logs in, polls for
  new tenders, downloads each PDF, pushes a `TenderDoc` onto Queue A, then loops.
  Never blocks on the later stages.
- **`workers/range_checker.py`** — reads Queue A, fills in value/dates (from the
  PDF if the scraper didn't already provide them), applies `RANGE_RULES`. Pass →
  Queue B; fail → `rejected/` + reason log.
- **`workers/uploader.py`** — reads Queue B, sends each tender to Lark. Success →
  `completed/`; recoverable failure → Queue Retry.
- **`workers/retry_worker.py`** — waits a cooldown and re-uploads failed docs up
  to `max_upload_attempts`, independently of the other stages.

## Adding a real site

The three portals (`mock`, `ireps`, `gem`) are registered in
`sites/registry.py`. `sites/ireps.py` and `sites/gem.py` are **skeletons** — the
pipeline is complete, you only fill in three methods:

```python
class IrepsScraper(BaseScraper):
    name = "ireps"
    def login(self): ...                     # authenticate
    def find_new_tenders(self) -> list[Listing]: ...   # read the results page
    def fetch_pdf(self, listing, dest) -> Path: ...    # download the PDF
```

Prefer reading `value` / `closing_date` straight into the `Listing` from the
results page — it's more reliable than extracting them from the PDF later
(`core/extract.py` is the fallback). Then enable the site in `config.SITES`.

## Publishing to Lark

`lark_client/client.py` has three interchangeable implementations behind one
`send(doc)` interface:

- **`bot`** — Open API. Uses `LARK_APP_ID` / `LARK_APP_SECRET`, uploads the
  actual PDF file, and posts an interactive card to a chat. This is the mode you
  publish as a real Lark app. Give the app the `im:message` and `im:resource`
  scopes and add the bot to the target chat (`LARK_RECEIVE_ID`).
- **`webhook`** — posts a card to a group incoming-webhook URL (no file upload).
  Quickest to test.
- **`noop`** — logs what would be sent. Default.

Use `LARK_API_BASE=https://open.feishu.cn` for Feishu (China) instead of global
Lark.

## Reliability notes

- **Dedup / crash recovery** — `.state/ledger.json` records every tender id
  seen and completed, so a restart never re-downloads or re-uploads.
- **Graceful shutdown** — Ctrl-C (or SIGTERM) drains in-flight work and stops
  each thread cleanly.
- **Isolation** — a crash in one site's scraper is caught, logged, and retried;
  it never takes down the pipeline.
```
