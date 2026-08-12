"""
The contract every site scraper implements. Worker 1 only ever talks to this
interface, so adding a portal means writing one subclass — nothing else changes.

Lifecycle per site:
    scraper = SomeScraper(site_config)
    scraper.login()
    while running:
        for listing in scraper.find_new_tenders():   # cheap: listing metadata
            doc = scraper.download(listing)           # expensive: fetch the PDF
            -> push doc onto Queue A
        sleep(poll_interval)
    scraper.close()
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from config import DOWNLOADS_DIR, SiteConfig
from core.logging_setup import get_logger
from core.models import TenderDoc


@dataclass
class Listing:
    """Lightweight tender reference discovered on a search/results page."""
    doc_id: str
    title: str = ""
    detail_url: str = ""
    pdf_url: str = ""
    # Anything already visible on the listing page — pass it through so we don't
    # have to re-extract it from the PDF later.
    value: float | None = None
    closing_date: date | None = None
    published_date: date | None = None
    extra: dict = field(default_factory=dict)


class BaseScraper(abc.ABC):
    """Base class for all portal scrapers."""

    #: unique key that config.SiteConfig.name refers to
    name: str = "base"

    def __init__(self, config: SiteConfig) -> None:
        self.config = config
        self.log = get_logger(f"site.{self.name}")
        self._logged_in = False

    # -- required per-site behaviour -------------------------------------- #
    @abc.abstractmethod
    def login(self) -> None:
        """Authenticate. Idempotent; may be called again after a session drop."""

    @abc.abstractmethod
    def find_new_tenders(self) -> list[Listing]:
        """Return current tender listings. Dedup happens upstream in the Ledger."""

    @abc.abstractmethod
    def fetch_pdf(self, listing: Listing, dest: Path) -> Path:
        """Download the tender's PDF to `dest` and return the final path."""

    # -- shared helpers ---------------------------------------------------- #
    def download(self, listing: Listing) -> TenderDoc:
        """Fetch the PDF and wrap everything in a TenderDoc for Queue A."""
        dest = DOWNLOADS_DIR / f"{self.name}_{_safe(listing.doc_id)}.pdf"
        path = self.fetch_pdf(listing, dest)
        return TenderDoc(
            doc_id=listing.doc_id,
            source=self.name,
            title=listing.title,
            detail_url=listing.detail_url,
            pdf_path=path,
            value=listing.value,
            closing_date=listing.closing_date,
            published_date=listing.published_date,
            metadata=dict(listing.extra),
        )

    def ensure_login(self) -> None:
        if not self._logged_in:
            self.login()
            self._logged_in = True

    def close(self) -> None:
        """Release resources (browser, session). Override if needed."""


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:100]
