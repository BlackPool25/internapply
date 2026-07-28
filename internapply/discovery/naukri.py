"""Naukri job scraper for InternApply.

Provides a :class:`NaukriScraper` class with two backends:

1. **HTTP (Primary)** — direct HTML scraping with httpx + BeautifulSoup.
   No API key needed.  This is the default path.
2. **Apify (Optional)** — enriched data via the Apify ``droidmaster/naukri-jobs-feed``
   actor when ``NAUKRI_APIFY_TOKEN`` is set in configuration.

Usage::

    from internapply.discovery.naukri import NaukriScraper

    scraper = NaukriScraper()
    jobs = await scraper.search(
        keywords=["python intern", "java intern"],
        locations=["Remote", "Bangalore"],
    )
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import Any, Self

from bs4 import BeautifulSoup
from httpx import AsyncClient
from loguru import logger

from internapply.config import get_config
from internapply.models import JobListing

__all__ = [
    "NaukriScraper",
    "_parse_salary",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NAUKRI_BASE = "https://www.naukri.com"
_DEFAULT_TIMEOUT = 30  # seconds
_MAX_RETRIES = 2  # additional retries beyond the initial attempt (3 total)
_MAX_PAGES = 2
_DELAY_MIN = 1.0
_DELAY_MAX = 2.0
_APIFY_ACTOR = "droidmaster/naukri-jobs-feed"

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Referer": "https://www.naukri.com/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ---------------------------------------------------------------------------
# Salary parsing
# ---------------------------------------------------------------------------

# Matches "₹6-12 LPA", "₹6 LPA", "₹6 - ₹12 Lakh", "₹600000/yr",
# "₹6,00,000/yr", "₹600000", "₹6" (treats bare small numbers as lakhs)
_SALARY_RE = re.compile(
    r"₹\s*([\d,]+)\s*(?:-\s*₹?\s*([\d,]+))?\s*"
    r"(LPA|Lakh|lakh|/Yr|/yr|/Year|/year)?"
)

# Matches "Not disclosed" and similar variants
_NOT_DISCLOSED_RE = re.compile(
    r"(Not\s*disclosed|Not\s*mentioned|NA|N/A|Not\s*known)",
    re.IGNORECASE,
)


def _parse_salary(text: str | None) -> tuple[int | None, int | None]:
    """Parse an Indian salary string to monthly INR (min, max).

    Handles these formats:

    * ``"₹6-12 LPA"`` → ``(50000, 100000)``  (yearly lakhs → monthly)
    * ``"₹6 LPA"`` → ``(50000, None)``
    * ``"₹600000/yr"`` → ``(50000, None)``
    * ``"₹6-12 Lakh"`` → ``(50000, 100000)``
    * ``"Not disclosed"`` → ``(None, None)``
    * ``None`` / ``""`` → ``(None, None)``

    Monthly conversion divides yearly amount by 12.  A bare number with no
    suffix and value < 1000 is assumed to be in lakhs (common Indian job
    convention).  A bare number >= 100000 without suffix is treated as a
    yearly amount.
    """
    if not text or not text.strip():
        return None, None

    text = text.strip()

    if _NOT_DISCLOSED_RE.search(text):
        return None, None

    # Strip commas from numbers so "6,00,000" becomes "600000"
    normalised = re.sub(r"(?<=\d),(?=\d)", "", text)

    m = _SALARY_RE.search(normalised)
    if m:
        min_val = _to_number(m.group(1))
        max_raw = m.group(2)
        max_val = _to_number(max_raw) if max_raw else None
        suffix = (m.group(3) or "").upper()

        min_monthly = _to_monthly(min_val, suffix)
        max_monthly = _to_monthly(max_val, suffix) if max_val is not None else None
        return min_monthly, max_monthly

    # Fallback: try to extract any number
    plain_num = re.search(r"₹?\s*([\d,]+)", normalised)
    if plain_num:
        val = _to_number(plain_num.group(1))
        if val < 1000:
            val *= 100000  # assume lakhs
        if val > 100000:
            return val // 12, None
        return val, None

    return None, None


def _to_number(s: str) -> int:
    """Convert a number string like ``"600000"`` or ``"12"`` to int."""
    return int(s.replace(",", ""))


def _to_monthly(val: int, suffix: str) -> int | None:
    """Convert a yearly salary value to monthly based on suffix.

    Args:
        val: The numeric salary value.
        suffix: Normalised uppercase suffix (e.g. ``"LPA"``, ``"/YR"``, ``""``).

    Returns:
        Monthly INR, or ``None`` if *val* is ``None``.
    """
    if suffix in ("LPA", "LAKH"):
        return (val * 100000) // 12
    if suffix in ("/YR", "/YEAR"):
        return val // 12
    # No suffix — treat as lakhs if it's a typical lakh-scale number (< 1000),
    # otherwise as a yearly amount if > 100000.
    if val < 1000:
        return (val * 100000) // 12
    if val > 100000:
        return val // 12
    return val


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def _build_search_url(
    keyword: str,
    location: str,
    internship: bool = False,
    page: int = 1,
) -> str:
    """Build a Naukri jobs search URL.

    Args:
        keyword: Search term (e.g. ``"python intern"``).
        location: Target location (e.g. ``"Bangalore"``).
        internship: If ``True`` use the ``{keyword}-internship-jobs-in-{location}``
            path (``False`` → ``{keyword}-jobs-in-{location}``).
        page: Page number (1-indexed).  Only appended when ``> 1``.

    Returns:
        A fully-formed Naukri search URL.
    """
    kw = _slugify(keyword)
    loc = _slugify(location)
    path = f"{kw}-{'internship-' if internship else ''}jobs-in-{loc}"
    url = f"{_NAUKRI_BASE}/{path}"
    if page > 1:
        url += f"?page={page}"
    return url


def _slugify(text: str) -> str:
    """Convert free text to a Naukri URL slug.

    * Lowercases the text.
    * Replaces whitespace and ``/`` with hyphens.
    * Strips non-alphanumeric chars except hyphens.
    * Collapses multiple hyphens.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[\s/]+", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------


class NaukriScraper:
    """Scrape job listings from Naukri.com.

    Two backends are supported:

    * **HTTP** (primary) — direct HTML scraping via httpx + BeautifulSoup.
    * **Apify** (fallback) — uses ``droidmaster/naukri-jobs-feed`` actor when
      ``NAUKRI_APIFY_TOKEN`` is configured.  Activated automatically when the
      HTTP backend returns no results for a keyword-location pair.

    Usage::

        scraper = NaukriScraper()
        jobs = await scraper.search(
            keywords=["python intern"],
            locations=["Remote", "Bangalore"],
        )
    """

    def __init__(self, config: Any | None = None) -> None:
        self._config = config or get_config()
        self._seen_urls: set[str] = set()
        self._client: AsyncClient | None = None

    # ── Public API ──────────────────────────────────────────────────────

    async def search(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
    ) -> list[JobListing]:
        """Search Naukri for internship listings.

        Iterates over every keyword-location combination using the HTTP
        backend first.  If HTTP returns no results for a combination **and**
        an Apify token is configured, falls back to the Apify backend.

        Results are post-filtered to keep only paid jobs (stipend > 0) whose
        location matches one of the target locations.

        Args:
            keywords: Search keywords.  Defaults to ``config.SEARCH_KEYWORDS``.
            locations: Target locations.  Defaults to ``config.SEARCH_LOCATIONS``.

        Returns:
            Deduplicated, filtered list of :class:`JobListing` objects.
        """
        keywords = keywords or self._config.SEARCH_KEYWORDS
        locations = locations or self._config.SEARCH_LOCATIONS
        all_jobs: list[JobListing] = []
        apify_token = self._config.NAUKRI_APIFY_TOKEN or ""

        for keyword in keywords:
            for location in locations:
                # ── HTTP backend (primary) ──
                logger.info(
                    "Naukri [HTTP] searching keyword={!r} location={!r}",
                    keyword,
                    location,
                )
                jobs = await self._search_http(keyword, location)

                # ── Apify fallback ──
                if not jobs and apify_token:
                    logger.info(
                        "Naukri HTTP empty for {!r}/{!r} — falling back to Apify",
                        keyword,
                        location,
                    )
                    jobs = await self._search_apify(keyword, location, apify_token)

                if jobs:
                    logger.info(
                        "Naukri found {} jobs for {!r}/{!r}",
                        len(jobs),
                        keyword,
                        location,
                    )
                    all_jobs.extend(jobs)
                else:
                    logger.warning(
                        "Naukri returned no jobs for {!r}/{!r} (both backends "
                        "exhausted)",
                        keyword,
                        location,
                    )

                await self._delay()

        # ── Post-filter: paid + location match ──
        filtered = self._apply_filters(all_jobs)
        logger.info(
            "Naukri total: {} raw → {} after post-filter (paid + location)",
            len(all_jobs),
            len(filtered),
        )
        return filtered

    # ── HTTP backend ────────────────────────────────────────────────────

    async def _search_http(
        self,
        keyword: str,
        location: str,
    ) -> list[JobListing]:
        """Scrape Naukri via direct HTTP GET + HTML parsing.

        Tries the general jobs URL first, then the internship-specific URL,
        with up to ``_MAX_PAGES`` pages per URL.

        Args:
            keyword: Search keyword.
            location: Target location.

        Returns:
            Parsed job listings (not yet post-filtered).
        """
        jobs: list[JobListing] = []

        for is_internship in (False, True):
            for page in range(1, _MAX_PAGES + 1):
                url = _build_search_url(
                    keyword, location, internship=is_internship, page=page,
                )
                html = await self._fetch(url)
                if html is None:
                    continue

                parsed = self._parse_listing_page(html, url)
                logger.debug(
                    "Parsed {} cards from {} (internship={}, page={})",
                    len(parsed),
                    url,
                    is_internship,
                    page,
                )
                if not parsed:
                    break  # No results on this page → no point paginating
                jobs.extend(parsed)
                await self._delay()

        return jobs

    async def _fetch(self, url: str) -> str | None:
        """Fetch a URL with retries and exponential backoff.

        Args:
            url: The URL to fetch.

        Returns:
            Response text, or ``None`` if all retries are exhausted.
        """
        client = await self._get_client()

        for attempt in range(1, _MAX_RETRIES + 2):  # 1-indexed, total 3
            try:
                resp = await client.get(
                    url,
                    headers=_HEADERS,
                    timeout=_DEFAULT_TIMEOUT,
                    follow_redirects=True,
                )
                resp.raise_for_status()
                return resp.text
            except Exception as exc:
                logger.debug(
                    "Fetch attempt {}/{} for {} failed: {!r}",
                    attempt,
                    _MAX_RETRIES + 1,
                    url,
                    exc,
                )
                if attempt <= _MAX_RETRIES:
                    wait = 2.0**attempt  # 2, 4 seconds
                    await asyncio.sleep(wait)
                else:
                    logger.warning(
                        "All fetch attempts exhausted for {}", url,
                    )
        return None

    def _parse_listing_page(
        self, html: str, source_url: str,
    ) -> list[JobListing]:
        """Parse Naukri HTML listing page into JobListing objects.

        Uses multiple selector strategies to handle Naukri's changing HTML
        structure (generated CSS module class names, attribute-only markers,
        etc.).

        Args:
            html: Raw HTML content.
            source_url: The URL the HTML was fetched from.

        Returns:
            List of deduplicated :class:`JobListing` objects.
        """
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[JobListing] = []

        # Try strategies from most reliable to most generic
        cards = (
            self._select_cards_by_attr(soup)
            or self._select_cards_by_class(soup, "jobTuple")
            or self._select_cards_by_class(soup, "jobCard")
            or self._select_cards_by_class(soup, "srp-jobtuple-wrapper")
            or self._select_cards_by_tag(soup, "article")
            or self._select_cards_by_class(soup, "info")
        )

        if not cards:
            logger.debug("No job cards found in Naukri HTML")
            return []

        for card in cards:
            try:
                listing = self._extract_listing(card)
                if listing is not None:
                    jobs.append(listing)
            except Exception as exc:
                logger.opt(exception=True).debug(
                    "Error extracting job from card: {!r}", exc,
                )

        return jobs

    # ── Card selectors ──────────────────────────────────────────────────

    @staticmethod
    def _select_cards_by_attr(soup: BeautifulSoup) -> list | None:
        """Cards identified by the ``data-job-id`` attribute (very reliable)."""
        cards = soup.find_all(lambda tag: tag.get("data-job-id") is not None)
        return cards if cards else None

    @staticmethod
    def _select_cards_by_class(
        soup: BeautifulSoup, class_name: str,
    ) -> list | None:
        """Cards identified by a CSS class (handles generated class names)."""
        pattern = re.compile(re.escape(class_name))
        cards = soup.find_all("div", class_=pattern)
        if not cards:
            # Also search within any element — Naukri may use <article> etc.
            cards = soup.find_all(class_=pattern)
        return cards if cards else None

    @staticmethod
    def _select_cards_by_tag(soup: BeautifulSoup, tag: str) -> list | None:
        """Fallback: select all elements of a given tag."""
        cards = soup.find_all(tag)
        return cards if cards else None

    # ── Field extraction ────────────────────────────────────────────────

    def _extract_listing(self, card: Any) -> JobListing | None:
        """Extract a JobListing from a single job card element.

        Returns ``None`` if the card lacks critical data (title or URL) or
        is a duplicate.
        """
        # ---- Title ----
        title_el = self._find_title_element(card)
        if not title_el:
            return None

        title = title_el.get_text(strip=True) or title_el.get("title", "") or ""

        # ---- URL ----
        href = title_el.get("href", "")
        if not href:
            return None
        job_url = href if href.startswith("http") else f"{_NAUKRI_BASE}{href}"

        if job_url in self._seen_urls:
            return None
        self._seen_urls.add(job_url)

        # ---- Company ----
        company_el = self._find_company_element(card)
        company = company_el.get_text(strip=True) if company_el else ""

        # ---- Location ----
        location_el = self._find_location_element(card)
        location = location_el.get_text(strip=True) if location_el else None

        # ---- Salary ----
        salary_el = self._find_salary_element(card)
        salary_text = salary_el.get_text(strip=True) if salary_el else None
        stipend_min, stipend_max = _parse_salary(salary_text)

        # ---- Skills ----
        skills: list[str] = []
        skills_el = card.find(
            "div", class_=lambda c: c and any("skill" in (cls or "").lower() for cls in (c if isinstance(c, list) else [c])),
        )
        if skills_el:
            skill_tags = skills_el.find_all("span") or skills_el.find_all("a")
            skills = [
                s.get_text(strip=True)
                for s in skill_tags
                if s.get_text(strip=True)
            ]

        # ---- Description ----
        desc_el = card.find(
            "div",
            class_=lambda c: c
            and any("desc" in (cls or "").lower() for cls in (c if isinstance(c, list) else [c])),
        )
        description = desc_el.get_text(strip=True) if desc_el else None

        # ---- Posted at ----
        posted_el = card.find(
            "span",
            class_=lambda c: c
            and any(
                kw in (cls or "").lower()
                for kw in ("posted", "time", "day")
                for cls in (c if isinstance(c, list) else [c])
            ),
            # Also match text containing "day" or "days"
        )
        posted_at = posted_el.get_text(strip=True) if posted_el else None
        if not posted_at:
            # Try finding by text content
            for span in card.find_all("span"):
                text = span.get_text(strip=True)
                if text and re.match(r"\d+\s*(day|hour|week|month)s?\s*ago", text, re.IGNORECASE):
                    posted_at = text
                    break

        # ---- Flags ----
        is_remote = False
        if location:
            loc_lower = location.lower()
            is_remote = any(
                kw in loc_lower for kw in ("remote", "work from home", "wfh")
            )

        is_paid = stipend_min is not None and stipend_min > 0

        return JobListing(
            title=title,
            company=company,
            location=location,
            stipend_min=stipend_min,
            stipend_max=stipend_max,
            stipend_raw=salary_text,
            skills=skills,
            description=description,
            source="naukri",
            url=job_url,
            posted_at=posted_at,
            is_paid=is_paid,
            is_remote=is_remote,
        )

    # ── Sub-element finders (overridable for testing) ───────────────────

    @staticmethod
    def _find_title_element(card: Any) -> Any | None:
        """Find the job title element within a card."""
        # Priority: anchor with title class, data-job-title attr, then href pattern
        return (
            card.find(
                "a",
                class_=lambda c: c
                and any("title" in (cls or "").lower() for cls in (c if isinstance(c, list) else [c])),
            )
            or card.find("a", attrs={"data-job-title": True})
            or card.find(
                "span",
                class_=lambda c: c
                and any("title" in (cls or "").lower() for cls in (c if isinstance(c, list) else [c])),
            )
            or card.find("a", href=re.compile(r"/jobs/"))
        )

    @staticmethod
    def _find_company_element(card: Any) -> Any | None:
        """Find the company name element within a card."""
        return (
            card.find(
                "a",
                class_=lambda c: c
                and any("comp" in (cls or "").lower() for cls in (c if isinstance(c, list) else [c])),
            )
            or card.find("a", attrs={"data-company-id": True})
        )

    @staticmethod
    def _find_location_element(card: Any) -> Any | None:
        """Find the location element within a card."""
        return (
            card.find(
                "span",
                class_=lambda c: c
                and any("loc" in (cls or "").lower() for cls in (c if isinstance(c, list) else [c])),
            )
            or card.find("span", attrs={"data-location": True})
            or card.find(
                "li",
                class_=lambda c: c
                and any("loc" in (cls or "").lower() for cls in (c if isinstance(c, list) else [c])),
            )
        )

    @staticmethod
    def _find_salary_element(card: Any) -> Any | None:
        """Find the salary/stipend element within a card."""
        return (
            card.find(
                "span",
                class_=lambda c: c
                and any("sal" in (cls or "").lower() for cls in (c if isinstance(c, list) else [c])),
            )
            or card.find(
                "span",
                class_=lambda c: c
                and any(
                    kw in (cls or "").lower()
                    for kw in ("stipend", "salary")
                    for cls in (c if isinstance(c, list) else [c])
                ),
            )
        )

    # ── Apify backend ───────────────────────────────────────────────────

    async def _search_apify(
        self,
        keyword: str,
        location: str,
        token: str,
    ) -> list[JobListing]:
        """Fetch job listings from the Apify Naukri actor.

        Args:
            keyword: Search keyword.
            location: Target location.
            token: Apify API token.

        Returns:
            List of :class:`JobListing` objects.
        """
        actor_url = (
            f"https://api.apify.com/v2/acts/{_APIFY_ACTOR}/run-sync-get-dataset-items"
        )
        params: dict[str, Any] = {"token": token}
        payload: dict[str, Any] = {
            "keyword": keyword,
            "location": location,
            "maxPages": _MAX_PAGES,
        }

        client = await self._get_client()

        try:
            resp = await client.post(
                actor_url,
                params=params,
                json=payload,
                headers={"User-Agent": _CHROME_UA},
                timeout=_DEFAULT_TIMEOUT + 30,  # Apify actor runs can be slow
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(
                "Apify API call failed for {!r}/{!r}: {!r}",
                keyword,
                location,
                exc,
            )
            return []

        if not isinstance(data, list):
            logger.warning(
                "Unexpected Apify response type for {!r}/{!r}: {}",
                keyword,
                location,
                type(data).__name__,
            )
            return []

        jobs: list[JobListing] = []
        for item in data:
            try:
                listing = self._apify_item_to_listing(item)
                if listing is not None:
                    jobs.append(listing)
            except Exception as exc:
                logger.opt(exception=True).debug(
                    "Error converting Apify item: {!r}", exc,
                )

        logger.debug("Apify returned {} items for {!r}/{!r}", len(jobs), keyword, location)
        return jobs

    def _apify_item_to_listing(self, item: dict[str, Any]) -> JobListing | None:
        """Convert an Apify API response item to a JobListing.

        Args:
            item: Single item from the Apify dataset.

        Returns:
            A :class:`JobListing`, or ``None`` if duplicate or lacks a URL.
        """
        url = item.get("url") or item.get("jobUrl") or ""
        if not url:
            return None
        if url in self._seen_urls:
            return None
        self._seen_urls.add(url)

        title = item.get("title") or item.get("jobName") or ""
        company = item.get("company") or item.get("companyName") or ""

        # Location may be a string or dict
        location_raw = item.get("location") or item.get("jobLocation") or None
        if isinstance(location_raw, dict):
            location_raw = location_raw.get("rawText") or str(location_raw)
        location = str(location_raw) if location_raw else None

        # Salary (Apify often provides richer salary fields)
        salary_raw = (
            item.get("salary")
            or item.get("salaryText")
            or item.get("salaryRaw")
            or None
        )
        stipend_min, stipend_max = _parse_salary(
            str(salary_raw) if salary_raw else None,
        )

        # Skills
        skills_raw = item.get("skills") or item.get("keySkills") or []
        if isinstance(skills_raw, str):
            skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        elif isinstance(skills_raw, list):
            skills = [str(s) for s in skills_raw]
        else:
            skills = []

        description = (
            item.get("description")
            or item.get("jobDescription")
            or None
        )
        posted_at = (
            item.get("postedDate")
            or item.get("postedAt")
            or None
        )

        # Flags
        is_remote = False
        if location:
            loc_lower = location.lower()
            is_remote = any(
                kw in loc_lower for kw in ("remote", "work from home", "wfh")
            )

        is_paid = stipend_min is not None and stipend_min > 0

        return JobListing(
            title=title,
            company=company,
            location=location,
            stipend_min=stipend_min,
            stipend_max=stipend_max,
            stipend_raw=str(salary_raw) if salary_raw else None,
            skills=skills,
            description=description,
            source="naukri",
            url=url,
            posted_at=posted_at,
            is_paid=is_paid,
            is_remote=is_remote,
        )

    # ── Post-filter ─────────────────────────────────────────────────────

    def _apply_filters(
        self, jobs: list[JobListing],
    ) -> list[JobListing]:
        """Post-filter job listings.

        * Keeps only paid jobs (stipend_min > 0).
        * Keeps only jobs whose location overlaps with one of the configured
          target locations (case-insensitive substring match).

        Args:
            jobs: Raw job listings.

        Returns:
            Filtered list.
        """
        target_locations = [loc.lower() for loc in self._config.SEARCH_LOCATIONS]
        result: list[JobListing] = []

        for job in jobs:
            # Paid check
            if not job.is_paid:
                continue

            # Location check
            if not job.location:
                continue
            loc_lower = job.location.lower()

            if not any(tloc in loc_lower for tloc in target_locations):
                continue

            result.append(job)

        return result

    # ── Helpers ─────────────────────────────────────────────────────────

    async def _get_client(self) -> AsyncClient:
        """Return (and lazily create) the shared httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = AsyncClient()
        return self._client

    async def _delay(self) -> None:
        """Wait a random interval for polite crawling."""
        await asyncio.sleep(random.uniform(_DELAY_MIN, _DELAY_MAX))

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
