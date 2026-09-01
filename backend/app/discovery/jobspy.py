"""JobSpy job scraper — free-only v1 no proxy routing.

Proxybroker service kept in docker but NOT wired for ATS/Hirist/free path.
Only wreq-js sidecar (WREQ_SIDECAR_URL) uses proxy-like routing.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

# Add project root to sys.path for imports
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_project_root))

from loguru import logger


class JobSpyScraper:
    """Scrapes job listings from multiple boards via JobSpy — free-only, no proxy."""

    def __init__(self, proxy_url: str | None = None) -> None:
        # free-only v1: do NOT route through proxybroker unless WREQ_SIDECAR_URL enabled
        wreq = os.getenv("WREQ_SIDECAR_URL", "")
        if proxy_url and wreq:
            self.proxy_url: str | None = proxy_url
        elif proxy_url and not wreq:
            logger.info("free-only v1: ignoring proxybroker proxy_url (WREQ_SIDECAR_URL not set)")
            self.proxy_url = None
        else:
            self.proxy_url = None
        self._jobspy_available = self._check_jobspy()

    def _check_jobspy(self) -> bool:
        """Check if python-jobspy is installed."""
        try:
            import jobspy  # noqa: F401
            return True
        except ImportError:
            logger.warning(
                "python-jobspy not installed. Install with: pip install python-jobspy"
            )
            return False

    def _check_proxy(self) -> bool:
        if not self.proxy_url:
            return False
        try:
            host, port = self.proxy_url.replace("socks5://", "").split(":")
            sock = socket.create_connection((host, int(port)), timeout=2)
            sock.close()
            return True
        except Exception:
            return False

    async def search(
        self,
        search_term: str,
        location: str = "India",
        results_wanted: int = 30,
        hours_old: int = 72,
        job_type: str = "internship",
        sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for jobs across multiple boards.

        Args:
            search_term: Job search query (e.g., "python backend intern")
            location: Location to search in
            results_wanted: Number of results per source
            hours_old: Only show jobs posted within this many hours
            job_type: "internship", "fulltime", "parttime", or "contract"
            sources: Which sources to search
                (default: ["linkedin", "indeed", "google"])

        Returns:
            List of job listing dicts with standardized fields
        """
        if not self._jobspy_available:
            logger.error("python-jobspy not available")
            return []

        try:
            from jobspy import scrape_jobs  # type: ignore[import-untyped]

            site_names = sources or ["linkedin", "indeed", "google"]
            proxy_usable = self._check_proxy() if self.proxy_url else False
            proxies: list[str] | None = [self.proxy_url] if proxy_usable and self.proxy_url else None
            if self.proxy_url and proxy_usable:
                logger.info("Using proxybroker2 at {} for JobSpy scrape", self.proxy_url)
            elif self.proxy_url:
                logger.warning("proxybroker2 not available \u2014 trying direct connection")
            else:
                logger.info("free-only v1: direct connection (no proxy) for {}", site_names)

            # JobSpy returns a pandas DataFrame
            import pandas as pd

            jobs_df: pd.DataFrame = scrape_jobs(
                site_name=site_names,
                search_term=search_term,
                location=location,
                results_wanted=results_wanted,
                hours_old=hours_old,
                job_type=job_type,
                proxies=proxies,
                linkedin_fetch_description=True,
                description_format="markdown",
            )

            if jobs_df.empty:
                logger.info(
                    "JobSpy returned no results for '{}' in '{}'",
                    search_term,
                    location,
                )
                return []

            # Convert DataFrame rows to standardized dicts
            jobs: list[dict[str, Any]] = []
            for _, row in jobs_df.iterrows():
                job: dict[str, Any] = {
                    "title": row.get("title", ""),
                    "company": row.get("company", ""),
                    "location": row.get("location", ""),
                    "description": row.get("description", ""),
                    "source": row.get("site", ""),
                    "url": row.get("job_url", ""),
                    "job_type": row.get("job_type", ""),
                    "is_remote": row.get("is_remote", False),
                    "posted_at": str(row.get("date_posted", "")),
                    "skills": [],  # JobSpy may not return skills directly
                }
                # Extract salary if available
                salary = row.get("salary", {})
                if isinstance(salary, dict):
                    job["stipend_min"] = salary.get("min_amount")
                    job["stipend_max"] = salary.get("max_amount")
                    job["stipend_currency"] = salary.get("currency")
                    job["stipend_interval"] = salary.get("interval")

                jobs.append(job)

            logger.info(
                "JobSpy returned {} jobs from {} for '{}' (sources: {})",
                len(jobs),
                ", ".join({j.get("source", "") for j in jobs}),
                search_term,
                sources or "default",
            )
            return jobs

        except ImportError as e:
            logger.error("Missing dependency: {}", e)
            return []
        except Exception as e:
            logger.error("JobSpy scrape failed: {}", e)
            return []

    async def search_keywords(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for multiple keyword/location combinations."""
        _keywords = keywords or ["python backend intern", "software engineer intern"]
        _locations = locations or ["Remote", "Bangalore"]

        all_jobs: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for keyword in _keywords:
            for location in _locations:
                jobs = await self.search(
                    search_term=keyword,
                    location=location,
                    results_wanted=20,
                )
                for job in jobs:
                    url = job.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_jobs.append(job)

        return all_jobs
