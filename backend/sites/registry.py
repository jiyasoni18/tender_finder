"""Maps a site name (from config.SiteConfig.name) to its scraper class."""

from __future__ import annotations

from config import SiteConfig
from sites.base import BaseScraper
from sites.gem import GemScraper
from sites.ireps import IrepsScraper
from sites.mock import MockScraper
from sites.tenderdetail import TenderDetailScraper

_REGISTRY: dict[str, type[BaseScraper]] = {
    MockScraper.name: MockScraper,
    IrepsScraper.name: IrepsScraper,
    GemScraper.name: GemScraper,
    TenderDetailScraper.name: TenderDetailScraper,
}


def build_scraper(config: SiteConfig) -> BaseScraper:
    try:
        cls = _REGISTRY[config.name]
    except KeyError:
        raise ValueError(
            f"No scraper registered for site '{config.name}'. "
            f"Known sites: {', '.join(sorted(_REGISTRY))}"
        )
    return cls(config)


def register(cls: type[BaseScraper]) -> type[BaseScraper]:
    """Decorator to plug in a new scraper: @register above your class."""
    _REGISTRY[cls.name] = cls
    return cls
