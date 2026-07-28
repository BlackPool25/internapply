"""Internshala HTTP job scraper for InternApply.

Scrapes internship listings from Internshala.com using HTTP requests and
BeautifulSoup HTML parsing.  No Playwright/Selenium needed because Internshala's
listing pages are server-rendered HTML.
"""

from __future__ import annotations

import asyncio
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

    Returns a dict with keys ``title``, ``company``, ``location``,
    ``stipend_raw``, ``skills``, ``url`` or ``None`` if the card does not
    contain a recognisable job title.
    """
    # ── Title (essential) ──────────────────────────────────────────
    title: str | None = None

    # Try: <h4 class="heading_4_*"><a>...</a></h4>
    h4 = card.find("h4", class_=re.compile(r"heading_4"))
    if h4 and h4.a:
        title = h4.a.get_text(strip=True)
    if not title:
        h4 = card.find("h4")
        if h4 and h4.a:
            title = h4.a.get_text(strip=True)
    if not title:
        a_tag = card.find("a", class_=re.compile(r"(internship|job)_title", re.IGNORECASE))
        if a_tag:
            title = a_tag.get_text(strip=True)
    if not title:
        a_tag = card.find("a", href=re.compile(r"^/(internship|job)/"))
        if a_tag:
            title = a_tag.get_text(strip=True)
    if not title:
        return None  # Title is mandatory

    # ── URL (essential) ────────────────────────────────────────────
    url: str | None = None
    for link in card.find_all("a", href=True):
        href: str = link["href"]  # type: ignore[assignment]
        if href.startswith(("/internship/", "/job/")):
            url = urljoin(BASE_URL, href)
            break
    if not url:
        return None  # URL is mandatory

    # ── Company ────────────────────────────────────────────────────
    company = ""
    h4_company = card.find("h4", class_=re.compile(r"heading_6"))
    if h4_company:
        company = h4_company.get_text(strip=True)
    if not company:
        company_div = card.find("div", class_=re.compile(r"(company|organization)", re.IGNORECASE))
        if company_div:
            company = company_div.get_text(strip=True)
    if not company:
        # Fallback: second h4 in the card
        h4s = card.find_all("h4")
        if len(h4s) > 1:
            company = h4s[1].get_text(strip=True)

    # ── Location ───────────────────────────────────────────────────
    location = ""
    loc_link = card.find("a", class_=re.compile(r"location", re.IGNORECASE))
    if loc_link:
        location = loc_link.get_text(strip=True)
    if not location:
        loc_div = card.find("div", class_=re.compile(r"location", re.IGNORECASE))
        if loc_div:
            location = loc_div.get_text(strip=True)

    # ── Stipend ────────────────────────────────────────────────────
    stipend_raw: str | None = None
    stipend_el = card.find(class_=re.compile(r"stipend", re.IGNORECASE))
    if stipend_el:
        stipend_raw = stipend_el.get_text(strip=True)

    # ── Skills ─────────────────────────────────────────────────────
    skills: list[str] = []
    skill_container = card.find("div", class_=re.compile(r"(skill|tag)", re.IGNORECASE))
    if skill_container:
        text = skill_container.get_text(strip=True)
        skills = [s.strip() for s in text.split(",") if s.strip()]
    if not skills:
        skill_spans = card.find_all("span", class_=re.compile(r"(skill|tag)", re.IGNORECASE))
        if skill_spans:
            skills = [s.get_text(strip=True) for s in skill_spans if s.get_text(strip=True)]

    return {
        "title": title,
        "company": company,
        "location": location,
        "stipend_raw": stipend_raw,
        "skills": skills,
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
        5. Deduplicate by URL.
        6. Convert to :class:`JobListing` models.

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

                # Apply filters & deduplicate
                batch: list[JobListing] = []
                for card in cards:
                    if not _passes_stipend_filter(card, self.min_stipend):
                        continue
                    if not _passes_location_filter(card, locations):
                        continue

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
            description="",
            source="internshala",
            url=card.get("url", ""),
            is_paid=card.get("is_paid", False),
            is_remote=is_remote,
        )
