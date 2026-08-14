"""
Pull structured fields (tender value, closing/publish dates) out of a PDF.

PDF layouts vary wildly between portals, so this uses tolerant regexes over the
raw text. Each site scraper can also pre-fill fields it already scraped from the
listing page (that's more reliable) — extraction here is the fallback.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from config import parse_date
from core.logging_setup import get_logger

log = get_logger("extract")

try:
    import pdfplumber  # type: ignore
except ImportError:  # keep the pipeline importable without the dep installed
    pdfplumber = None


# ₹ 12,34,567.00  |  Rs. 1234567  |  INR 1,234,567  |  1234567/-
_VALUE_RE = re.compile(
    r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(Lakhs?|Lacs?|L|Crores?|Cr|K|M)?|([0-9][0-9,]{4,}(?:\.[0-9]+)?)\s*/-",
    re.IGNORECASE,
)

# Any dd-mm-yyyy / dd/mm/yyyy / dd Mon yyyy style date.
_DATE_RE = re.compile(
    r"\b(\d{1,2}[-/.\s](?:\d{1,2}|[A-Za-z]{3,9})[-/.\s]\d{2,4})\b"
)

# Lines that usually carry the closing/submission deadline.
_CLOSING_HINTS = ("closing", "last date", "due date", "submission", "bid end", "end date")
_PUBLISH_HINTS = ("published", "publish date", "advertisement", "issue date", "start date")


def read_pdf_text(pdf_path: Path, max_pages: int = 10) -> str:
    if pdfplumber is None:
        log.warning("pdfplumber not installed; cannot read %s", pdf_path.name)
        return ""
    try:
        parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:max_pages]:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception as exc:  # corrupt/scanned PDF, etc.
        log.warning("Failed to read %s: %s", pdf_path.name, exc)
        return ""


def _clean_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


# Regex to find value NEAR specific keyword labels (searched first, highest priority)
_LABELLED_VALUE_RE = re.compile(
    r"(?:estimated\s+cost|advertised\s+value|advertisement\s+value|tender\s+value|approximate\s+value"
    r"|contract\s+value|value\s+of\s+work|estimate(?:\s+of\s+work)?)"
    r"[^0-9₹Rr]{0,60}"            # allow label/table separators (including newlines from PDF tables)
    r"(?:₹\s*|Rs?\.?\s*|INR\s*)?"
    r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(Lakhs?|Lacs?|L|Crores?|Cr|K|M)?",
    re.IGNORECASE | re.DOTALL,
)


def extract_value(text: str) -> float | None:
    """
    Return the tender/contract value from PDF text.
    Strategy:
    1. Look for value next to known labels (Estimated Cost, Advertised Value, etc.)
       — this avoids picking up Earnest Money Deposit or Tender Fees.
    2. Fall back to the largest ₹/Rs.  amount if no labelled value is found.
    """
    # --- Strategy 1: label-anchored -----------------------------------------
    for m in _LABELLED_VALUE_RE.finditer(text):
        num = _clean_number(m.group(1))
        unit = (m.group(2) or "").lower()
        if num is not None:
            if "lakh" in unit or "lac" in unit or unit == "l": num *= 100000
            elif "crore" in unit or "cr" in unit: num *= 10000000
            elif "k" in unit: num *= 1000
            elif "m" in unit: num *= 1000000

            if num >= 1000:          # ignore obviously-tiny amounts
                return num

    # --- Strategy 2: largest currency-prefixed amount -----------------------
    best: float | None = None
    for m in _VALUE_RE.finditer(text):
        num = _clean_number(m.group(1) or m.group(3))
        unit = (m.group(2) or "").lower() if m.group(1) else ""
        if num is None:
            continue
            
        if "lakh" in unit or "lac" in unit or unit == "l": num *= 100000
        elif "crore" in unit or "cr" in unit: num *= 10000000
        elif "k" in unit: num *= 1000
        elif "m" in unit: num *= 1000000
            
        if best is None or num > best:
            best = num
    return best


def _date_near_hints(text: str, hints: tuple[str, ...]) -> date | None:
    for line in text.splitlines():
        low = line.lower()
        if any(h in low for h in hints):
            m = _DATE_RE.search(line)
            if m:
                parsed = parse_date(m.group(1))
                if parsed:
                    return parsed
    return None


def extract_dates(text: str) -> tuple[date | None, date | None]:
    """Return (closing_date, published_date), either may be None."""
    closing = _date_near_hints(text, _CLOSING_HINTS)
    published = _date_near_hints(text, _PUBLISH_HINTS)
    return closing, published


def enrich_from_pdf(doc) -> None:
    """
    Fill any missing value/date fields on a TenderDoc from its PDF. Fields the
    scraper already set (more trustworthy) are left untouched.
    """
    if doc.pdf_path is None or not Path(doc.pdf_path).exists():
        return
    text = read_pdf_text(Path(doc.pdf_path))
    if not text:
        return

    if doc.value is None:
        doc.value = extract_value(text)
    if doc.closing_date is None or doc.published_date is None:
        closing, published = extract_dates(text)
        doc.closing_date = doc.closing_date or closing
        doc.published_date = doc.published_date or published
