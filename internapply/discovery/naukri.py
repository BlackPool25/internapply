"""Naukri job scraper for InternApply.

Provides a :class:`NaukriScraper` class that uses Apify as the sole backend
for fetching job listings from Naukri.com.  Direct HTTP scraping is not
supported — Naukri is a Next.js SPA protected by Akamai.

Usage::

    from internapply.discovery.naukri import NaukriScraper

    async with NaukriScraper() as scraper:
        jobs = await scraper.search(
            keywords=["python intern", "java intern"],
            locations=["Remote", "Bangalore"],
        )
"""

from __future__ import annotations

import re
from typing import Any, Self

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

_APIFY_ACTOR = "droidmaster/naukri-jobs-feed"
_APIFY_TIMEOUT = 90  # seconds — Apify actor runs can be slow
_APIFY_MAX_PAGES = 2

# ---------------------------------------------------------------------------
# Salary parsing
# ---------------------------------------------------------------------------

_SALARY_RE = re.compile(
    r"₹\s*([\d,]+)\s*(?:-\s*₹?\s*([\d,]+))?\s*"
    r"(LPA|Lakh|lakh|/Yr|/yr|/Year|/year)?"
)

_NOT_DISCLOSED_RE = re.compile(
    r"(Not\s*disclosed|Not\s*mentioned|NA|N/A|Not\s*known)",
    re.IGNORECASE,
)


def _parse_salary(text: str | None) -> tuple[int | None, int | None]:
    """Parse an Indian salary string to monthly INR (min, max).

    Handles these formats:

    * ``"₹6-12 LPA"`` — ``(50000, 100000)``  (yearly lakhs → monthly)
    * ``"₹6 LPA"`` — ``(50000, None)``
    * ``"₹600000/yr"`` — ``(50000, None)``
    * ``"₹6-12 Lakh"`` — ``(50000, 100000)``
    * ``"Not disclosed"`` — ``(None, None)``
    * ``None`` / ``""`` — ``(None, None)``

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
# Scraper
# ---------------------------------------------------------------------------


class NaukriScraper:
    """Scrape job listings from Naukri.com via Apify.

    Uses the ``droidmaster/naukri-jobs-feed`` Apify actor.  Requires
    ``NAUKRI_APIFY_TOKEN`` to be set in the application configuration.

    Usage::

        async with NaukriScraper() as scraper:
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
        """Search Naukri for internship listings via the Apify backend.

        Requires ``NAUKRI_APIFY_TOKEN`` to be configured — raises
        :class:`ValueError` if it is missing.

        Results are post-filtered to keep only paid jobs (stipend > 0) whose
        location matches one of the target locations.

        Args:
            keywords:  Search keywords.  Defaults to ``config.SEARCH_KEYWORDS``.
            locations: Target locations.  Defaults to ``config.SEARCH_LOCATIONS``.

        Returns:
            Deduplicated, filtered list of :class:`JobListing` objects.
        """
        keywords = keywords or self._config.SEARCH_KEYWORDS
        locations = locations or self._config.SEARCH_LOCATIONS
        apify_token = self._config.NAUKRI_APIFY_TOKEN or ""

        if not apify_token:
            msg = (
                "NAUKRI_APIFY_TOKEN is not configured. "
                "Set it in your configuration (e.g. config.toml or "
                "NAUKRI_APIFY_TOKEN environment variable) to use the "
                "Naukri scraper."
            )
            logger.error(msg)
            raise ValueError(msg)

        all_jobs: list[JobListing] = []

        for keyword in keywords:
            for location in locations:
                logger.info(
                    "Naukri [Apify] searching keyword={!r} location={!r}",
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
                        "Naukri returned no jobs for {!r}/{!r}",
                        keyword,
                        location,
                    )

        # ── Post-filter: paid + location match ──
        filtered = self._apply_filters(all_jobs)
        logger.info(
            "Naukri total: {} raw → {} after post-filter (paid + location)",
            len(all_jobs),
            len(filtered),
        )
        return filtered

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
            "maxPages": _APIFY_MAX_PAGES,
        }

        client = await self._get_client()

        try:
            resp = await client.post(
                actor_url,
                params=params,
                json=payload,
                timeout=_APIFY_TIMEOUT,
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

        logger.debug(
            "Apify returned {} items for {!r}/{!r}", len(jobs), keyword, location,
        )
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

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
