"""Hunter.io email finder for discovering hiring manager emails.

Provides an :class:`EmailFinder` class that uses the Hunter.io API v2
to find work email addresses for a given domain, then filters and
sorts them to surface the best hiring-manager candidates.

Usage::

    from internapply.outreach.email_finder import EmailFinder, EmailContact

    finder = EmailFinder()
    contacts = await finder.find_contacts("https://example.com/jobs/123")
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from httpx import AsyncClient
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select

from internapply.config import get_config
from internapply.database import ORMEmailLookup, get_session

__all__ = [
    "EmailContact",
    "EmailFinder",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HUNTER_API_BASE = "https://api.hunter.io/v2"

# Position keywords used to identify hiring-manager roles.
_HIRING_KEYWORDS: frozenset[str] = frozenset({
    "recruiter",
    "hiring",
    "talent",
    "hr",
    "manager",
    "head",
    "director",
    "vp",
    "chief",
})

_SENIORITY_SCORES: dict[str, int] = {
    "chief": 4,
    "vp": 4,
    "head": 4,
    "director": 3,
    "manager": 2,
    "recruiter": 1,
    "hiring": 1,
    "talent": 1,
    "hr": 1,
}

_MAX_CANDIDATES = 3
_DEFAULT_TIMEOUT = 15  # seconds


# ---------------------------------------------------------------------------
# EmailContact model
# ---------------------------------------------------------------------------


class EmailContact(BaseModel):
    """A single email address found via the Hunter.io API."""

    email: str
    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None
    confidence: int | None = None  # 0–100
    source: str = "hunter"


# ---------------------------------------------------------------------------
# EmailFinder
# ---------------------------------------------------------------------------


class EmailFinder:
    """Find hiring-manager email addresses for a company domain.

    Wraps the Hunter.io ``/v2/domain-search`` endpoint with result
    caching in the local ``email_lookups`` table, position-based
    filtering, and seniority scoring.

    Args:
        api_key: Hunter.io API key.  If ``None`` the key is read from
            the application config (``HUNTER_API_KEY``).
    """

    def __init__(self, api_key: str | None = None) -> None:
        if api_key is not None:
            self._api_key = api_key
        else:
            cfg = get_config()
            self._api_key = cfg.HUNTER_API_KEY

        if not self._api_key:
            logger.warning(
                "HUNTER_API_KEY is not configured — "
                "EmailFinder will return empty results"
            )

    # ── Public API ────────────────────────────────────────────────────

    async def find_contacts(
        self,
        job_url: str,
        company_name: str | None = None,
    ) -> list[EmailContact]:
        """Find hiring-manager contacts for a company.

        Internally extracts (or guesses) the domain from *job_url* and
        *company_name*, then delegates to :meth:`find_contacts_for_domain`.

        Args:
            job_url:
                Full URL of the job listing (e.g.
                ``"https://www.linkedin.com/jobs/view/123"``).
            company_name:
                Optional company name used as a fallback when the domain
                cannot be extracted from *job_url*.

        Returns:
            A list of up to 3 :class:`EmailContact` objects, sorted by
            estimated seniority (most senior first).
        """
        domain = self._extract_domain(job_url, company_name)
        if not domain:
            logger.warning(
                "Could not determine domain from job_url={!r} company_name={!r}",
                job_url,
                company_name,
            )
            return []
        return await self.find_contacts_for_domain(domain)

    async def find_contacts_for_domain(self, domain: str) -> list[EmailContact]:
        """Look up hiring-manager emails for *domain*.

        Checks the local ``email_lookups`` cache first; makes a real
        API call only when no cached result exists.

        Args:
            domain: The company domain (e.g. ``"acme.com"``).

        Returns:
            A sorted, filtered list of up to 3 contacts (may be empty).
        """
        domain = domain.lower().strip()

        # 1. Try cache
        cached = await self._cached_lookup(domain)
        if cached is not None:
            logger.info("Returned {} cached contacts for domain {}", len(cached), domain)
            return cached

        # 2. Real API call
        if not self._api_key:
            logger.warning("No Hunter API key — cannot fetch contacts for {}", domain)
            return []

        contacts = await self._hunter_api_call(domain)

        # 3. Persist to cache
        await self._cache_result(domain, contacts)
        return contacts

    # ── Domain extraction ─────────────────────────────────────────────

    @staticmethod
    _JOB_BOARD_DOMAINS = frozenset({
        "internshala.com", "linkedin.com", "naukri.com", "indeed.com",
        "glassdoor.com", "monster.com", "angel.co", "wellfound.com",
        "google.com", "yahoo.com", "bing.com",
    })

    @classmethod
    def _extract_domain(cls, url: str, company_name: str | None) -> str:
        """Extract a company domain from *url* or *company_name*.

        Priority:
        1. Parse the netloc from the URL.  If it's a known job board
           (internshala.com, linkedin.com, etc.), skip it and fall
           through to the company-name guess.
        2. Build a domain from *company_name* by lowercasing, removing
           spaces, and appending ``.com``.

        Returns the domain string (e.g. ``"acme.com"``) or empty string.
        """
        url = url.strip()
        if url:
            parsed = urlparse(url)
            netloc = parsed.netloc or parsed.path
            if ":" in netloc:
                netloc = netloc.split(":")[0]
            if netloc:
                netloc = netloc.removeprefix("www.").lower()
                if netloc not in cls._JOB_BOARD_DOMAINS and "." in netloc:
                    return netloc

        # Fallback: company name → domain guess
        if company_name:
            name = company_name.strip().lower()
            name = name.replace(" ", "").replace("-", "").replace(",", "")
            for suffix in ["privatelimited", "pvtltd", "ltd", "limited", "private"]:
                name = name.replace(suffix, "")
            name = name.strip()
            if not name.endswith(".com"):
                name += ".com"
            if "." in name:
                return name

        return ""

    # ── Filtering & scoring ───────────────────────────────────────────

    @classmethod
    def _filter_by_position(cls, contacts: list[dict[str, Any]]) -> list[EmailContact]:
        """Filter raw Hunter.io contacts to hiring-manager roles only.

        Keeps contacts whose ``position`` field contains at least one of
        the hiring-related keywords, then scores by seniority and
        returns the top ``_MAX_CANDIDATES``.

        Args:
            contacts: Raw email dicts from the Hunter API response
                ``data.emails[]``.

        Returns:
            A sorted list of up to 3 :class:`EmailContact` objects.
        """
        matched: list[EmailContact] = []

        for raw in contacts:
            position = (raw.get("position") or "").lower()
            if not position:
                continue

            # Keyword check
            if not any(kw in position for kw in _HIRING_KEYWORDS):
                continue

            matched.append(
                EmailContact(
                    email=raw.get("email", ""),
                    first_name=raw.get("first_name"),
                    last_name=raw.get("last_name"),
                    position=raw.get("position"),
                    confidence=raw.get("confidence"),
                    source="hunter",
                )
            )

        # Sort: seniority desc, then confidence desc
        matched.sort(
            key=lambda c: (
                cls._seniority_score(c.position or ""),
                c.confidence or 0,
            ),
            reverse=True,
        )

        return matched[:_MAX_CANDIDATES]

    @staticmethod
    def _seniority_score(position: str) -> int:
        """Return a numeric seniority score for *position*.

        Higher values indicate a more senior / decision-making role.
        """
        pos_lower = position.lower()
        best = 0
        for keyword, score in _SENIORITY_SCORES.items():
            if keyword in pos_lower:
                best = max(best, score)
        return best

    # ── Caching ───────────────────────────────────────────────────────

    @staticmethod
    async def _cached_lookup(domain: str) -> list[EmailContact] | None:
        """Return cached contacts for *domain*, or ``None`` if not found.

        Queries the ``email_lookups`` table for a row matching *domain*
        and deserialises the stored JSON back into :class:`EmailContact`
        objects.
        """
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(ORMEmailLookup).where(ORMEmailLookup.domain == domain)
                )
                row = result.scalar_one_or_none()
                if row is None:
                    return None
                raw_list: list[dict[str, Any]] = json.loads(row.emails_json)
                return [EmailContact(**item) for item in raw_list]
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).debug("Cache lookup failed for domain {}", domain)
            return None

    @staticmethod
    async def _cache_result(domain: str, contacts: list[EmailContact]) -> None:
        """Persist *contacts* to the ``email_lookups`` table.

        Uses an upsert pattern — replaces the cached data if the domain
        already exists, inserts otherwise.
        """
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(ORMEmailLookup).where(ORMEmailLookup.domain == domain)
                )
                existing = result.scalar_one_or_none()

                emails_json = json.dumps(
                    [c.model_dump() for c in contacts],
                    default=str,
                )
                now = datetime.now(UTC).replace(tzinfo=None)

                if existing:
                    existing.emails_json = emails_json
                    existing.cached_at = now
                else:
                    session.add(
                        ORMEmailLookup(
                            domain=domain,
                            emails_json=emails_json,
                            cached_at=now,
                        )
                    )
                await session.commit()
                logger.debug("Cached {} contacts for domain {}", len(contacts), domain)
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("Failed to cache contacts for {}", domain)

    # ── Hunter.io API ─────────────────────────────────────────────────

    async def _hunter_api_call(self, domain: str) -> list[EmailContact]:
        """Call the Hunter.io ``/v2/domain-search`` endpoint.

        Filters the response to ``type="work"`` emails, then runs the
        result through :meth:`_filter_by_position`.

        Gracefully handles common HTTP error statuses.

        Args:
            domain: The company domain to query.

        Returns:
            A (possibly empty) list of filtered :class:`EmailContact`.
        """
        url = f"{HUNTER_API_BASE}/domain-search"
        params = {"domain": domain, "api_key": self._api_key}
        headers = {"Accept": "application/json"}

        logger.info("Calling Hunter.io API for domain {}", domain)

        try:
            async with AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.get(url, params=params, headers=headers)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hunter.io request failed for {}: {!r}", domain, exc)
            return []

        # -- HTTP status handling --
        if resp.status_code in (401, 403):
            logger.warning(
                "Hunter.io auth error (HTTP {}) for {} — check HUNTER_API_KEY",
                resp.status_code,
                domain,
            )
            return []

        if resp.status_code == 429:
            logger.warning(
                "Hunter.io rate limit hit (HTTP 429) for {} — "
                "free tier allows ~50 requests/month",
                domain,
            )
            return []

        if resp.status_code != 200:
            logger.warning(
                "Hunter.io returned HTTP {} for {}: {}",
                resp.status_code,
                domain,
                resp.text[:500],
            )
            return []

        # -- Parse JSON response --
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hunter.io returned non-JSON for {}: {!r}", domain, exc)
            return []

        # Hunter response shape: { "data": { "emails": [...] } }
        payload: dict[str, Any] = data.get("data", {})
        all_emails: list[dict[str, Any]] = payload.get("emails", [])

        # Keep only work-type emails
        work_emails = [e for e in all_emails if e.get("type") == "work"]

        if not work_emails:
            logger.info("No work-type emails found for {}", domain)
            return []

        # Filter for hiring-manager positions
        filtered = self._filter_by_position(work_emails)
        logger.info(
            "Hunter.io: {} work emails → {} hiring-manager candidates for {}",
            len(work_emails),
            len(filtered),
            domain,
        )
        return filtered
