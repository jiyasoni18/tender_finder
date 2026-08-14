"""
An offline scraper that fabricates tenders and writes real (tiny) PDFs to disk.

Its only job is to let you run `python main.py` and watch the full pipeline —
download -> range check -> Lark -> retry — work end to end before you've written
a single line of real portal scraping. Disable it in config once real sites work.
"""

from __future__ import annotations

import itertools
from datetime import date, timedelta
from pathlib import Path

from sites.base import BaseScraper, Listing

# Deterministic (no randomness) so behaviour is reproducible. Mix of values and
# dates so some pass the range check and some get rejected.
_SAMPLES = [
    # (value, days_until_close)
    (2_500_000, 15),   # pass
    (50_000, 10),      # reject: below min
    (9_000_000, 20),   # pass
    (75_000_000, 30),  # reject: above max
    (1_200_000, -3),   # reject: already closed
    (400_000, 25),     # pass
]


class MockScraper(BaseScraper):
    name = "mock"

    def __init__(self, config) -> None:
        super().__init__(config)
        self._counter = itertools.count(1)
        self._batch = 0
        self._per_batch = int(config.options.get("docs_per_batch", 5))

    def login(self) -> None:
        self.log.info("Mock login OK (no network)")

    def find_new_tenders(self) -> list[Listing]:
        # Emit one batch, then stop producing so the demo naturally winds down.
        if self._batch >= 3:
            return []
        self._batch += 1

        listings: list[Listing] = []
        for _ in range(self._per_batch):
            n = next(self._counter)
            value, days = _SAMPLES[(n - 1) % len(_SAMPLES)]
            listings.append(Listing(
                doc_id=f"MOCK-{n:04d}",
                title=f"Supply and installation lot #{n}",
                detail_url=f"mock://tender/{n}",
                value=value,
                closing_date=date.today() + timedelta(days=days),
                published_date=date.today(),
            ))
        self.log.info("Discovered %d mock tenders (batch %d)", len(listings), self._batch)
        return listings

    def fetch_pdf(self, listing: Listing, dest: Path) -> Path:
        # Write a minimal but valid PDF so downstream file handling is exercised.
        dest.write_bytes(_tiny_pdf(listing.title))
        return dest


def _tiny_pdf(title: str) -> bytes:
    text = f"Tender: {title}".replace("(", "").replace(")", "")
    body = (
        "%PDF-1.4\n"
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 120]"
        "/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        f"4 0 obj<</Length {len(text) + 40}>>stream\n"
        f"BT /F1 12 Tf 20 60 Td ({text}) Tj ET\n"
        "endstream endobj\n"
        "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        "trailer<</Root 1 0 R>>\n%%EOF"
    )
    return body.encode("latin-1", errors="replace")
