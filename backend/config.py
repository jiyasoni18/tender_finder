"""
Central configuration for the tender pipeline.

Everything the operator tunes lives here. Secrets (passwords, Lark app
credentials) are read from environment variables so they never get committed.
Copy `.env.example` to `.env` and fill it in, then load it (see README).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent

# Allow persisting custom save path
_save_path_file = BASE_DIR / ".save_path"
if _save_path_file.exists():
    _custom_path = _save_path_file.read_text().strip()
    DOWNLOADS_DIR = Path(_custom_path) if _custom_path else BASE_DIR / "downloads"
else:
    DOWNLOADS_DIR = BASE_DIR / "downloads"
REJECTED_DIR = BASE_DIR / "rejected"     # failed range check
COMPLETED_DIR = BASE_DIR / "completed"   # uploaded to Lark successfully
LOGS_DIR = BASE_DIR / "logs"
STATE_DIR = BASE_DIR / ".state"          # dedup / crash-recovery bookkeeping
REPORTS_DIR = BASE_DIR / "reports"       # generated PDF summaries

for _d in (DOWNLOADS_DIR, REJECTED_DIR, COMPLETED_DIR, LOGS_DIR, STATE_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
# Range rules  (Worker 2)  -- edit these to match what you want to keep
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RangeRules:
    # Tender value window, in rupees. Set a bound to None to disable it.
    min_value: float | None = 5_000_000           # ₹50 lakh minimum
    max_value: float | None = 500_000_000          # ₹5 crore maximum

    # Closing-date window. A tender passes only if its closing date is on or
    # after `closing_from` and on or before `closing_to`. None disables a bound.
    closing_from: date | None = date.today()    # don't bother with expired ones
    closing_to: date | None = None

    # Optional publish-date window (when the tender was advertised).
    published_from: date | None = None
    published_to: date | None = None

    # If a required field can't be extracted from the PDF, do we reject it
    # (True, safe default) or let it pass (False)?
    reject_on_missing_value: bool = False   # let tenders pass if value can't be read from PDF
    reject_on_missing_date: bool = False


RANGE_RULES = RangeRules()


# --------------------------------------------------------------------------- #
# Sites  (Worker 1)  -- add one entry per portal you scrape
# --------------------------------------------------------------------------- #
@dataclass
class SiteConfig:
    name: str                       # must match a registered scraper (see sites/registry.py)
    enabled: bool = True
    base_url: str = ""
    username_env: str = ""          # name of the env var holding the username
    password_env: str = ""          # name of the env var holding the password
    poll_interval_seconds: int = 60  # Worker 1 "wait 10 sec" knob, per site
    # Free-form extra settings a specific scraper may need (search filters, etc.)
    options: dict = field(default_factory=dict)

    @property
    def username(self) -> str:
        return os.getenv(self.username_env, "") if self.username_env else ""

    @property
    def password(self) -> str:
        return os.getenv(self.password_env, "") if self.password_env else ""


SITES: list[SiteConfig] = [
    # The mock site needs no credentials and runs offline. It exists so you can
    # watch the whole pipeline work before wiring real portals. Disable it once
    # the real scrapers are ready.
    SiteConfig(
        name="mock",
        enabled=_get_bool("ENABLE_MOCK_SITE", True),
        poll_interval_seconds=8,
        options={"docs_per_batch": 5},
    ),
    SiteConfig(
        name="ireps",
        enabled=_get_bool("ENABLE_IREPS", False),
        base_url="https://www.ireps.gov.in",
        username_env="IREPS_USER",
        password_env="IREPS_PASS",
        poll_interval_seconds=3600,
        options={
            # e.g. restrict to a department / tender type. Consumed by sites/ireps.py
            "tender_type": "works",
        },
    ),
    SiteConfig(
        name="gem",
        enabled=_get_bool("ENABLE_GEM", False),
        base_url="https://bidplus.gem.gov.in",
        username_env="GEM_USER",
        password_env="GEM_PASS",
        poll_interval_seconds=120,
        options={},
    ),
    SiteConfig(
        name="tenderdetail",
        enabled=False,
        base_url="https://www.tenderdetail.com",
        username_env="TENDERDETAIL_USER",
        password_env="TENDERDETAIL_PASS",
        poll_interval_seconds=3600,
        options={
            "keywords": ["Cctv", "cc", "smart City gift city"]
        },
    ),
]


# --------------------------------------------------------------------------- #
# Lark  (Worker 3)  -- how passed tenders get published
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LarkConfig:
    # "bot"     -> use Open API (app_id/app_secret): uploads the PDF + rich card.
    #              This is the mode you publish as a real Lark app.
    # "webhook" -> post a message to a group webhook (quick, no file upload).
    # "noop"    -> log only; don't call Lark. Handy for local testing.
    mode: str = os.getenv("LARK_MODE", "noop")

    # Bot mode credentials (from your Lark app's developer console).
    app_id: str = os.getenv("LARK_APP_ID", "")
    app_secret: str = os.getenv("LARK_APP_SECRET", "")
    # Where to deliver: a chat id (oc_...) the bot is a member of.
    receive_id: str = os.getenv("LARK_RECEIVE_ID", "")
    receive_id_type: str = os.getenv("LARK_RECEIVE_ID_TYPE", "chat_id")
    # Lark vs Feishu base host. Global Lark by default.
    api_base: str = os.getenv("LARK_API_BASE", "https://open.larksuite.com")

    # Webhook mode.
    webhook_url: str = os.getenv("LARK_WEBHOOK_URL", "")
    # Optional signing secret if the webhook has signature verification on.
    webhook_secret: str = os.getenv("LARK_WEBHOOK_SECRET", "")

    # Bitable credentials
    bitable_app_token: str = os.getenv("LARK_BITABLE_APP_TOKEN", "")
    bitable_table_id: str = os.getenv("LARK_BITABLE_TABLE_ID", "")


LARK = LarkConfig()


# --------------------------------------------------------------------------- #
# Pipeline behaviour
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PipelineConfig:
    # Retry worker
    retry_delay_seconds: int = 30      # "wait 30 sec" before re-uploading
    max_upload_attempts: int = 5       # give up after this many tries

    # Graceful shutdown: how long to wait for in-flight jobs on Ctrl-C.
    shutdown_grace_seconds: int = 20

    # Bounded queues create back-pressure so a fast downloader can't blow up
    # memory when Lark is slow. 0 = unbounded.
    queue_maxsize: int = 0
    
    # Maximum number of documents to download per site per run. 0 = unlimited.
    max_downloads: int = int(os.getenv("MAX_DOWNLOADS", "0"))

    log_level: str = os.getenv("LOG_LEVEL", "INFO")


PIPELINE = PipelineConfig()


def parse_date(value: str) -> date | None:
    """Best-effort date parser used by config overrides / extractors."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None
