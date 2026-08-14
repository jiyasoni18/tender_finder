"""The range-check decision (Worker 2's brain), driven by config.RANGE_RULES."""

from __future__ import annotations

from dataclasses import dataclass

from config import RANGE_RULES, RangeRules
from core.models import TenderDoc


@dataclass
class Verdict:
    passed: bool
    reason: str = ""  # why it was rejected (empty when passed)


def check_ranges(doc: TenderDoc, rules: RangeRules = RANGE_RULES) -> Verdict:
    """Apply value + date-window rules. First failing rule wins the reason."""

    # --- Value window ----------------------------------------------------- #
    if doc.value is None:
        if rules.reject_on_missing_value:
            return Verdict(False, "value could not be extracted")
    else:
        if rules.min_value is not None and doc.value < rules.min_value:
            return Verdict(False, f"value {doc.value:,.0f} < min {rules.min_value:,.0f}")
        if rules.max_value is not None and doc.value > rules.max_value:
            return Verdict(False, f"value {doc.value:,.0f} > max {rules.max_value:,.0f}")

    # --- Closing-date window ---------------------------------------------- #
    if doc.closing_date is None:
        if rules.reject_on_missing_date:
            return Verdict(False, "closing date could not be extracted")
    else:
        if rules.closing_from and doc.closing_date < rules.closing_from:
            return Verdict(False, f"closes {doc.closing_date} before {rules.closing_from}")
        if rules.closing_to and doc.closing_date > rules.closing_to:
            return Verdict(False, f"closes {doc.closing_date} after {rules.closing_to}")

    # --- Publish-date window (optional) ----------------------------------- #
    if doc.published_date is not None:
        if rules.published_from and doc.published_date < rules.published_from:
            return Verdict(False, f"published {doc.published_date} before {rules.published_from}")
        if rules.published_to and doc.published_date > rules.published_to:
            return Verdict(False, f"published {doc.published_date} after {rules.published_to}")

    return Verdict(True)
