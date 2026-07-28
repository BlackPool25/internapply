"""Internshala HTTP job scraper for InternApply.

Scrapes internship listings from Internshala.com using HTTP requests and
BeautifulSoup HTML parsing.  No Playwright/Selenium needed because Internshala's
listing pages are server-rendered HTML.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any, Self
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from loguru import logger

from internapply.models import JobListing

# ---------------------------------------------------------------------------
# Stipend parsing
# ---------------------------------------------------------------------------

_STIPEND_RANGE_RE = re.compile(r"₹\s*([\d,]+)\s*[-–]\s*([\d,]+)")
_STIPEND_SINGLE_RE = re.compile(r"₹\s*([\d,]+)")
_STIPEND_RANGE_NO_SYMBOL_RE = re.compile(
    r"([\d,]+)\s*[-–]\s*([\d,]+)\s*(?:/month|per month|lump\s*sum)?",
)
_STIPEND_PLAIN_RE = re.compile(r"(\d{3,})\s*(?:/month|per month|lump\s*sum)")
_UNPAID_RE = re.compile(
    r"\b(unpaid|performance\s*based|negotiable|not\s*paid|no\s*stipend|volunteer)\b",
    re.IGNORECASE,
)


def _clean_number(text: str) -> int:
    """Convert a comma-formatted number string to an integer."""
    return int(text.replace(",", "").strip())


def parse_stipend(raw: str | None) -> tuple[int | None, int | None, bool]:
    """Parse an Internshala stipend string into ``(min, max, is_paid)``.

    Known formats handled::

        "₹5,000 /month"          -> (5000, 5000, True)
        "₹10,000-15,000 /month"  -> (10000, 15000, True)
        "₹15,000 lump sum"       -> (15000, 15000, True)
        "Unpaid"                  -> (0, 0, False)
        "Performance based"       -> (0, 0, False)

    Args:
        raw: The raw stipend text from the listing page.

    Returns:
        A tuple ``(min_stipend, max_stipend, is_paid)``.  When the text
        cannot be parsed, ``min_stipend`` and ``max_stipend`` are ``None``.
    """
    if not raw or not raw.strip():
        return None, None, False

    stripped = raw.strip()

    # 1. Unpaid / non-monetary keywords — short-circuit
    if _UNPAID_RE.search(stripped):
        return 0, 0, False

    # 2. ₹ range: "₹10,000-15,000 /month"
    m = _STIPEND_RANGE_RE.search(stripped)
    if m:
        try:
            v_min = _clean_number(m.group(1))
            v_max = _clean_number(m.group(2))
            return v_min, v_max, True
        except (ValueError, IndexError):
            pass

    # 3. ₹ single: "₹5,000 /month" or "₹15,000 lump sum"
    m = _STIPEND_SINGLE_RE.search(stripped)
    if m:
        try:
            val = _clean_number(m.group(1))
            return val, val, True
        except (ValueError, IndexError):
            pass

    # 4. Plain range (no ₹ symbol): "5,000-10,000 /month"
    m = _STIPEND_RANGE_NO_SYMBOL_RE.search(stripped)
    if m:
        try:
            v_min = _clean_number(m.group(1))
            v_max = _clean_number(m.group(2))
            return v_min, v_max, True
        except (ValueError, IndexError):
            pass

    # 5. Plain number: "5000/month"
    m = _STIPEND_PLAIN_RE.search(stripped)
    if m:
        try:
            val = _clean_number(m.group(1))
            return val, val, True
        except (ValueError, IndexError):
            pass

    # 6. Last resort — any 3+ digit number in the string
    digits = re.findall(r"\d{3,}", stripped)
    if digits:
        return int(digits[0]), int(digits[0]), True

    return None, None, False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://internshala.com"
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Rate limiting
REQUEST_DELAY_MIN = 2.0
REQUEST_DELAY_MAX = 3.0

# Retry config
MAX_RETRIES = 2
RETRY_DELAYS: list[float] = [2.0, 4.0]

# Pagination
PAGINATION_MAX = 3

# ── Minimum result threshold for health-check warning ──
HEALTH_CHECK_KEYWORD = "python"


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert free-text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _build_slug_url(keyword: str, location: str) -> str:
    """Slug-based Internshala URL.

    Example: ``https://internshala.com/internships/python-internship-in-bangalore/``
    """
    return f"{BASE_URL}/internships/{_slugify(keyword)}-internship-in-{_slugify(location)}/"


def _build_search_url(keyword: str, location: str, page: int = 1) -> str:
    """Query-param Internshala URL.

    Example: ``https://internshala.com/internships/?q=python&location=Bangalore``
    """
    params: dict[str, str | int] = {"q": keyword, "location": location}
    if page > 1:
        params["page"] = page
    return f"{BASE_URL}/internships/?{urlencode(params)}"


def _pagination_url(base_url: str, page: int) -> str:
    """Append the page fragment to a base Internshala URL."""
    if page == 1:
        return base_url
    if "?" in base_url:
        sep = "&" if base_url[-1] != "?" else ""
        return f"{base_url}{sep}page={page}"
    return base_url.rstrip("/") + f"/page/{page}/"


# ---------------------------------------------------------------------------
# Page fetching with retry + exponential back-off
# ---------------------------------------------------------------------------


async def _fetch_page(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetch *url* with automatic retries.

    Returns the response text on success, ``None`` on permanent failure.
    Only 200 responses are considered successful.  4xx/5xx are logged and
    skipped; network errors trigger retries with exponential back-off.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.get(
                url, headers=DEFAULT_HEADERS, follow_redirects=True, timeout=30.0
            )
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
        ) as exc:
            last_exc = exc
            logger.warning(
                "Network error fetching {} (attempt {}/{}): {}",
                url,
                attempt + 1,
                MAX_RETRIES + 1,
                exc,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAYS[attempt])
            continue
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning(
                "HTTP error fetching {} (attempt {}/{}): {}",
                url,
                attempt + 1,
                MAX_RETRIES + 1,
                exc,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAYS[attempt])
            continue

        if resp.status_code == 200:
            return resp.text

        if resp.status_code in (403, 404):
            logger.info("HTTP {} for {} — not retrying", resp.status_code, url)
            return None

        if resp.status_code >= 500:
            logger.warning(
                "HTTP {} for {} (attempt {}/{})",
                resp.status_code,
                url,
                attempt + 1,
                MAX_RETRIES + 1,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAYS[attempt])
            continue

        logger.warning("Unexpected HTTP {} for {}", resp.status_code, url)
        return None

    logger.error(
        "Failed to fetch {} after {} attempts — last error: {}",
        url,
        MAX_RETRIES + 1,
        last_exc,
    )
    return None


# ---------------------------------------------------------------------------
# HTML parsing — multiple selector fallbacks
# ---------------------------------------------------------------------------


def _extract_card_data(card: Tag) -> dict[str, Any] | None:
    """Extract job fields from a single Internshala listing ``<div>``.

    Uses text-based parsing (split on delimiters) to handle frequent
    Internshala HTML structure changes without per-selector maintenance.

    Returns a dict with keys ``title``, ``company``, ``location``,
    ``stipend_raw``, ``skills``, ``url`` or ``None`` if the card does not
    contain a recognisable job title.
    """
    # Get all text parts as a flat list
    text = card.get_text("\n", strip=True)
    parts = [p.strip() for p in text.split("\n") if p.strip()]

    if not parts:
        return None

    # ── URL (essential — find first internship/job link) ─────────────
    url: str | None = None
    for link in card.find_all("a", href=True):
        href: str = link["href"]
        if href.startswith(("/internship/", "/job/")):
            url = urljoin(BASE_URL, href)
            break
    if not url:
        return None

    # ── Title (essential — first part or first <a> text) ────────────
    title = parts[0]
    if not title or len(title) < 3:
        a_tag = card.find("a", href=re.compile(r"^/(internship|job)/"))
        if a_tag:
            title = a_tag.get_text(strip=True)
    if not title or len(title) < 3:
        return None

    # ── Company (first non-excluded part after title, scan all parts) ─
    company_excluded = {
        "actively hiring", "work from home", "hybrid", "part-time",
        "full-time", "internship", "job", "intern", "start date",
        "duration", "skills", "about", "requirements", "perks",
        "stipend", "locations", "remote", "apply by",
    }
    company = ""
    for p in parts[1:]:
        if not p:
            continue
        p_lower = p.lower().strip()
        if (
            len(p_lower) > 2
            and p_lower not in company_excluded
            and "₹" not in p
            and "/month" not in p
            and "months" not in p
            and not any(c in p_lower for c in ["day", "week", "hour"])
            and not re.match(r"^\d", p)
        ):
            company = p
            break

    # ── Location (text-based scanning — primary) ──────────────────
    location = ""
    location_tokens = [
        "remote", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad",
        "pune", "chennai", "kolkata", "work from home", "work-from-home",
        "gurgaon", "gurugram", "noida", "ahmedabad", "india",
    ]
    for p in parts:
        pl = p.lower()
        if any(c in pl for c in location_tokens):
            location = p
            break

    # ── Stipend ──────────────────────────────────────────────────
    _STIPEND_EXTRACT_RE = re.compile(
        r"(?:₹|Rs\.?\s*|INR\s*)\s*([\d,]+(?:\s*[-–]\s*[\d,]+)?)",
        re.IGNORECASE,
    )
    stipend_raw = ""
    for p in parts:
        if "₹" in p or re.search(r"(?:Rs\.?|INR)", p, re.IGNORECASE):
            stipend_raw = p
            break
    if not stipend_raw:
        for p in parts:
            if re.search(r"\d{3,}\s*(?:/month|per month|lump\s*sum)", p, re.IGNORECASE):
                stipend_raw = p
                break

    # ── Posted-at ────────────────────────────────────────────────
    _POSTED_AT_RE = re.compile(
        r"(?i)\b(today|yesterday|(\d+)\s*days?\s*ago|(\d+)\s*week?s?\s*ago|(\d+)\s*month?s?\s*ago)\b"
    )
    posted_at = ""
    for p in parts:
        m = _POSTED_AT_RE.search(p)
        if m:
            posted_at = m.group(0)
            break

    # ── Skills ───────────────────────────────────────────────────
    skills: list[str] = []
    skill_container = card.find("div", class_=re.compile(r"(skill|tag)", re.IGNORECASE))
    if skill_container:
        skills_text = skill_container.get_text(strip=True)
        skills = [s.strip() for s in skills_text.split(",") if s.strip()]

    return {
        "title": title,
        "company": company,
        "location": location,
        "stipend_raw": stipend_raw,
        "skills": skills,
        "posted_at": posted_at,
        "url": url,
    }


def _parse_page(html: str, source_url: str) -> list[dict[str, Any]]:
    """Parse all internship cards from an HTML listing page.

    Returns a list of extracted card data dicts.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Try multiple card selectors in priority order
    card_selectors: list[dict[str, Any]] = [
        {"class_": "individual_internship"},
        {"class_": re.compile(r"individual_internship")},
        {"class_": re.compile(r"internship_card", re.IGNORECASE)},
        {"class_": re.compile(r"internship_listing", re.IGNORECASE)},
        {"class_": "internship_card"},
    ]

    cards: list[Tag] = []
    for selector in card_selectors:
        found = soup.find_all("div", **selector)
        if found:
            cards = found
            logger.debug("Found {} cards with selector {}", len(cards), selector)
            break

    # Last resort: any element with "internship" in an id or class
    if not cards:
        cards = soup.select('div[id*="internship" i], div[class*="internship" i]')
        if cards:
            logger.debug("Found {} cards via fallback CSS selector", len(cards))

    if not cards:
        logger.warning("No internship cards found on {}", source_url)
        body = soup.find("body")
        if body:
            sample = body.get_text(strip=True)[:500]
            logger.debug("Page body sample (500 chars): {}", sample)
        return []

    results: list[dict[str, Any]] = []
    for card in cards:
        try:
            data = _extract_card_data(card)
            if data:
                results.append(data)
        except Exception as exc:
            logger.debug("Card extraction error: {}", exc)
            continue

    return results


# ---------------------------------------------------------------------------
# Scraping orchestration for one keyword + location
# ---------------------------------------------------------------------------


async def _scrape_keyword_location(
    client: httpx.AsyncClient,
    keyword: str,
    location: str,
) -> list[dict[str, Any]]:
    """Scrape Internshala for one keyword + location.

    Tries the slug-based URL first; if no cards are found, falls back to the
    query-param URL.  Paginates up to ``PAGINATION_MAX`` pages per URL pattern.
    """
    all_cards: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    url_patterns = [
        _build_slug_url(keyword, location),
        _build_search_url(keyword, location),
    ]

    for base_url in url_patterns:
        for page in range(1, PAGINATION_MAX + 1):
            page_url = _pagination_url(base_url, page)
            html = await _fetch_page(client, page_url)
            if html is None:
                continue

            cards = _parse_page(html, page_url)
            if not cards:
                break  # No results → stop paginating this URL pattern

            for card in cards:
                u = card.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    all_cards.append(card)

            # Polite delay between pages
            await asyncio.sleep(
                REQUEST_DELAY_MIN + random.random() * (REQUEST_DELAY_MAX - REQUEST_DELAY_MIN)
            )

        # If we got cards from the first URL pattern, skip the second
        if all_cards:
            break

    return all_cards


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------


def _passes_stipend_filter(card: dict[str, Any], min_stipend: int) -> bool:
    """Check whether *card* meets the minimum stipend threshold.

    Mutates *card* in-place by adding ``stipend_min``, ``stipend_max``, and
    ``is_paid`` keys derived from parsing ``stipend_raw``.
    """
    min_val, max_val, is_paid = parse_stipend(card.get("stipend_raw"))
    card["stipend_min"] = min_val
    card["stipend_max"] = max_val
    card["is_paid"] = is_paid

    return bool(
        is_paid
        and min_val is not None
        and min_val > 0
        and min_val >= min_stipend
    )


def _passes_location_filter(card: dict[str, Any], allowed_locations: list[str]) -> bool:
    """Check whether *card*'s location is allowed.

    A listing passes if:
    - its location text *contains* (case-insensitive) any of the allowed
      location tokens, OR
    - it is marked as remote / work-from-home.
    """
    loc = (card.get("location") or "").lower().strip()

    # Remote / WFH is always accepted
    if "remote" in loc or "work from home" in loc or "work-from-home" in loc:
        return True

    for allowed in allowed_locations:
        al = allowed.lower().strip()
        if al and al in loc:
            return True

    return False


# ---------------------------------------------------------------------------
# Keyword filter
# ---------------------------------------------------------------------------


def _passes_keyword_filter(title: str, keywords: list[str]) -> bool:
    """Check whether *title* contains any significant token from *keywords*.

    A token is significant if it is at least 3 characters long.  The match
    is case-insensitive.

    Args:
        title: The job title to test.
        keywords: Search phrases (e.g. ``"python backend"``).

    Returns:
        ``True`` if at least one significant word from any keyword appears
        in the title.
    """
    title_lower = title.lower()
    # Collect all words >= 3 chars from all keyword phrases
    tokens: set[str] = set()
    for phrase in keywords:
        tokens.update(word.lower() for word in phrase.split() if len(word) >= 3)
    return any(token in title_lower for token in tokens)


# ---------------------------------------------------------------------------
# Detail-page enrichment (JSON-LD)
# ---------------------------------------------------------------------------


def _parse_job_posting_jsonld(html: str) -> dict[str, Any] | None:
    """Extract ``JobPosting`` structured data from a detail page.

    Finds the first ``<script type="application/ld+json">`` tag whose
    parsed JSON has ``@type`` equal to ``"JobPosting"`` (or containing it
    in a list) and returns selected fields.

    Returns a dict with keys *description*, *company*, *location*,
    *stipend_raw*, *skills*, *title* — or ``None`` when no valid
    ``JobPosting`` block is found.
    """
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue

        # Normalise @type to a list for uniform checking
        raw_type = data.get("@type") or data.get("type")
        types = [raw_type] if isinstance(raw_type, str) else (raw_type or [])

        if "JobPosting" not in types:
            continue

        title = data.get("title") or ""

        desc_raw = data.get("description") or ""
        if desc_raw:
            desc_soup = BeautifulSoup(desc_raw, "html.parser")
            description = desc_soup.get_text(separator=" ", strip=True)
        else:
            description = ""

        org = data.get("hiringOrganization") or {}
        if isinstance(org, dict):
            company = org.get("name", "")
        else:
            company = str(org) if org else ""

        location = ""
        loc = data.get("jobLocation") or {}
        if isinstance(loc, dict):
            addr = loc.get("address") or {}
            if isinstance(addr, dict):
                location = addr.get("addressLocality", "")
            elif isinstance(addr, str):
                location = addr

        stipend_raw = ""
        salary = data.get("baseSalary") or {}
        if isinstance(salary, dict):
            value = salary.get("value") or {}
            if isinstance(value, dict):
                min_v = value.get("minValue")
                max_v = value.get("maxValue")
                if min_v is not None and max_v is not None:
                    stipend_raw = f"₹{min_v:,.0f}-{max_v:,.0f} /month"
                elif min_v is not None:
                    stipend_raw = f"₹{min_v:,.0f} /month"

        skills_raw = data.get("skills") or ""
        if isinstance(skills_raw, str) and skills_raw:
            skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        elif isinstance(skills_raw, list):
            skills = [str(s).strip() for s in skills_raw if s]
        else:
            skills = []

        return {
            "title": title,
            "company": company,
            "location": location,
            "stipend_raw": stipend_raw,
            "skills": skills,
            "description": description,
        }

    return None


async def _enrich_card(
    client: httpx.AsyncClient,
    card: dict[str, Any],
) -> dict[str, Any]:
    """Fetch the detail page for *card* and override fields from JSON-LD.

    This is called **after** filters have already been applied, so the
    extra HTTP request is only made for listings that will actually be
    returned.

    Gracefully handles fetch failures — returns the original *card*
    unchanged when the detail page cannot be loaded or contains no
    ``JobPosting`` structured data.
    """
    url = card.get("url")
    if not url:
        return card

    try:
        resp = await client.get(url, headers=DEFAULT_HEADERS, follow_redirects=True, timeout=5.0)
        resp.raise_for_status()
    except Exception:
        logger.debug("Failed to fetch detail page for {} — skipping enrichment", url)
        return card

    parsed = _parse_job_posting_jsonld(resp.text)
    if parsed is None:
        return card

    for key in ("title", "company", "location", "stipend_raw", "skills", "description"):
        if parsed.get(key):
            card[key] = parsed[key]

    return card


# ---------------------------------------------------------------------------
# InternshalaScraper
# ---------------------------------------------------------------------------


class InternshalaScraper:
    """Scrape Internshala internship listings via HTTP + BeautifulSoup.

    Usage::

        scraper = InternshalaScraper(min_stipend=5000)
        jobs = await scraper.search(
            keywords=["python", "java backend"],
            locations=["Remote", "Bangalore"],
        )
    """

    def __init__(self, min_stipend: int = 5000) -> None:
        """Initialise the scraper.

        Args:
            min_stipend: Minimum monthly stipend in INR.  Listings below
                this threshold are excluded.  Defaults to 5000.
        """
        self.min_stipend = min_stipend
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # HTTPX client management
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create or return the shared HTTPX client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTPX client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Main search entry-point
    # ------------------------------------------------------------------

    async def search(
        self,
        keywords: list[str],
        locations: list[str],
    ) -> list[JobListing]:
        """Scrape Internshala for every combination of *keywords* × *locations*.

        Steps:
        1. For each ``(keyword, location)`` pair, fetch listing pages.
        2. Parse HTML to extract card data.
        3. Apply stipend filter (``min_stipend`` threshold).
        4. Apply location filter.
        5. Apply keyword filter on card title.
        6. Fetch detail pages for passing cards and enrich with JSON-LD.
        7. Deduplicate by URL.
        8. Convert to :class:`JobListing` models.

        Args:
            keywords: Search terms (e.g. ``"python backend intern"``).
            locations: Target cities or ``"Remote"``.

        Returns:
            A list of deduplicated, filtered :class:`JobListing` objects.
        """
        client = await self._get_client()
        all_jobs: list[JobListing] = []
        seen_urls: set[str] = set()
        total_raw = 0
        health_check_failed = False

        for keyword in keywords:
            for location in locations:
                logger.info(
                    "Internshala scrape — keyword={!r}, location={!r}",
                    keyword,
                    location,
                )

                try:
                    cards = await _scrape_keyword_location(client, keyword, location)
                except Exception as exc:
                    logger.error(
                        "Internshala scrape failed for {!r} + {!r}: {}",
                        keyword,
                        location,
                        exc,
                    )
                    continue

                raw_count = len(cards)
                total_raw += raw_count

                # Health check: "python" returning 0 across all locations
                if keyword.lower().strip() == HEALTH_CHECK_KEYWORD and raw_count == 0:
                    health_check_failed = True

                # Apply filters, keyword check, enrichment & deduplicate
                batch: list[JobListing] = []
                for card in cards:
                    if not _passes_stipend_filter(card, self.min_stipend):
                        continue
                    if not _passes_location_filter(card, locations):
                        continue
                    if not _passes_keyword_filter(card.get("title", ""), keywords):
                        continue

                    card = await _enrich_card(client, card)

                    job_url = card.get("url", "")
                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    job = self._card_to_joblisting(card)
                    batch.append(job)

                all_jobs.extend(batch)
                logger.info(
                    "Internshala {!r} + {!r}: {} raw -> {} after filters",
                    keyword,
                    location,
                    raw_count,
                    len(batch),
                )

                # Polite delay between keyword+location requests
                await asyncio.sleep(
                    REQUEST_DELAY_MIN + random.random() * (REQUEST_DELAY_MAX - REQUEST_DELAY_MIN)
                )

        if health_check_failed:
            logger.critical(
                "Internshala returned 0 results for keyword={!r} across all "
                "locations.  Site structure may have changed or requests are "
                "being blocked.",
                HEALTH_CHECK_KEYWORD,
            )

        logger.info(
            "Internshala scrape complete: {} raw results -> {} final jobs",
            total_raw,
            len(all_jobs),
        )
        return all_jobs

    # ------------------------------------------------------------------
    # Model conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _card_to_joblisting(card: dict[str, Any]) -> JobListing:
        """Convert an extracted card dict into a ``JobListing`` model."""
        location = (card.get("location") or "").strip()
        loc_lower = location.lower()
        is_remote = bool(
            "remote" in loc_lower
            or "work from home" in loc_lower
            or "work-from-home" in loc_lower
        )

        return JobListing(
            title=card.get("title", ""),
            company=card.get("company", ""),
            location=location,
            stipend_min=card.get("stipend_min"),
            stipend_max=card.get("stipend_max"),
            stipend_raw=card.get("stipend_raw"),
            skills=card.get("skills", []),
            description=card.get("description", ""),
            source="internshala",
            url=card.get("url", ""),
            posted_at=card.get("posted_at"),
            is_paid=card.get("is_paid", False),
            is_remote=is_remote,
        )
