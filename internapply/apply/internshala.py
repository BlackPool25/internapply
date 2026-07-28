"""Internshala auto-apply via Playwright.

Provides :class:`InternshalaSubmitter` which navigates to an Internshala
internship listing, fills the application form (cover letter, resume),
and submits it with rate-limit and human-like behaviour guards.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import Browser, Page

from internapply.apply.browser import BrowserManager
from internapply.database import ORMApplication, get_session
from internapply.models import JobListing

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_APPLICATIONS_PER_SESSION = 5
"""Hard limit on applications in one automated session (3-5 min gap each)."""

MAX_APPLICATIONS_PER_DAY = 15
"""Internshala-implicit daily limit we enforce ourselves."""

MIN_DELAY_BETWEEN_JOBS_S = 180  # 3 minutes
MAX_DELAY_BETWEEN_JOBS_S = 300  # 5 minutes

MIN_HUMAN_DELAY_MS = 2000
MAX_HUMAN_DELAY_MS = 5000

# ---------------------------------------------------------------------------
# Submitter
# ---------------------------------------------------------------------------


class InternshalaSubmitter:
    """Submit applications on Internshala via Playwright.

    Usage::

        submitter = InternshalaSubmitter()
        await submitter.start_session()
        success = await submitter.apply(job)
        await submitter.close_session()

    Or rely on auto-start (``apply()`` calls ``start_session()`` if the
    browser is not yet connected).
    """

    def __init__(self, browser_manager: BrowserManager | None = None) -> None:
        self._bm = browser_manager or BrowserManager()
        self._browser: Browser | None = None
        self._app_count: int = 0

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def start_session(self) -> None:
        """Start (or connect to) a browser for this submitter session.

        Tries CDP first (attach to a real Chrome), then falls back to
        launching a headless Chromium.
        """
        if self._browser is not None:
            return

        # Try CDP first: check if Chrome is already running with --remote-debugging-port
        import socket

        cdp_url = None
        config = get_config()
        configured_url = getattr(config, "CDP_URL", None)
        if configured_url:
            cdp_url = configured_url
            logger.info("Using configured CDP URL: {}", cdp_url)
        else:
            # Try to find a running Chrome by probing common ports around 9222
            for port in range(9222, 9242):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.3)
                    result = s.connect_ex(("127.0.0.1", port))
                    s.close()
                    if result == 0:
                        cdp_url = f"http://127.0.0.1:{port}"
                        logger.info("Found Chrome on port {}", port)
                        break
                except Exception:
                    continue

        if cdp_url:
            try:
                self._browser = await self._bm.connect_cdp(endpoint_url=cdp_url)
                logger.info("Connected to existing Chrome via CDP")
            except Exception as exc:
                logger.warning("CDP connect failed: {} — launching headless", exc)
                self._browser = await self._bm.launch_headless()
        else:
            logger.info("No existing Chrome found — launching headless Chromium")
            self._browser = await self._bm.launch_headless()

    async def close_session(self) -> None:
        """Close the browser and release all resources."""
        await self._bm.close()
        self._browser = None
        logger.info("Internshala submitter session closed")

    # ------------------------------------------------------------------
    # Main apply method
    # ------------------------------------------------------------------

    async def apply(
        self,
        job: JobListing,
        tailored_resume_path: str | None = None,
        cover_letter_path: str | None = None,
        dry_run: bool = False,
    ) -> bool:
        """Apply to a single Internshala internship.

        Steps
        -----
        1. Navigate to ``job.url``
        2. Click "Apply Now" button
        3. Fill cover letter if field exists
        4. Upload resume (use existing PDF if no tailored one)
        5. Answer screening questions (if any)
        6. Submit
        7. Verify success
        8. Update Application status in DB

        Parameters
        ----------
        job:
            The job listing to apply to.
        tailored_resume_path:
            Optional path to a tailored resume PDF.  If ``None``, the
            default resume is used (searched in ``profile/resume.pdf``).
        cover_letter_path:
            Optional path to a cover letter text file.
        dry_run:
            If ``True``, simulate the apply flow without submitting.

        Returns
        -------
        ``True`` if the application was submitted successfully.

        Raises
        ------
        RuntimeError
            If the daily or per-session limit has been reached.
        """
        # ---- Auto-start session if needed --------------------------------
        if self._browser is None:
            await self.start_session()

        # ---- Rate-limit checks -------------------------------------------
        self._check_limits()

        if dry_run:
            logger.info(f"[DRY RUN] Would apply to: {job.title} @ {job.company}")
            return True

        # ---- Resolve paths ------------------------------------------------
        resume_path = tailored_resume_path or self._resolve_default_resume()

        # ---- Fresh context per job ----------------------------------------
        context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = await context.new_page()

        try:
            success = await self._execute_apply(
                page=page,
                job=job,
                resume_path=resume_path,
                cover_letter_path=cover_letter_path,
            )
            if success:
                self._app_count += 1
                await self._record_application(job)
            return success
        finally:
            await context.close()

            # Rate-limit pause between jobs (skip the wait on the *last* job
            # of a session, since there is nothing after it).
            if success and self._app_count < MAX_APPLICATIONS_PER_SESSION:
                delay = random.uniform(
                    MIN_DELAY_BETWEEN_JOBS_S, MAX_DELAY_BETWEEN_JOBS_S
                )
                logger.info(
                    "Waiting {:.0f}s before next application "
                    "(applied {}/{} this session)...",
                    delay,
                    self._app_count,
                    MAX_APPLICATIONS_PER_SESSION,
                )
                await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Internal apply flow
    # ------------------------------------------------------------------

    async def _execute_apply(
        self,
        page: Page,
        job: JobListing,
        resume_path: str,
        cover_letter_path: str | None,
    ) -> bool:
        """Execute the actual apply flow on a single page.

        Returns ``True`` if the application was submitted and verified.
        """
        app_dir = Path.cwd() / "applications" / str(job.id or "unknown")
        app_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Navigate to job URL
            logger.info(f"Navigating to: {job.url}")
            await page.goto(job.url, wait_until="networkidle", timeout=30000)
            await self._human_delay(page)

            # 2. Click "Apply Now"
            if not await self._click_apply_now(page):
                await self._capture_screenshot(
                    page, str(app_dir / "apply_not_found.png")
                )
                logger.warning(
                    "Apply Now button not found for {} @ {} — skipping",
                    job.title,
                    job.company,
                )
                return False

            await self._human_delay(page)

            # 3. Wait for application form to appear
            await page.wait_for_timeout(3000)
            await self._human_delay(page)

            # 4. Fill cover letter if field exists
            if cover_letter_path:
                await self._fill_cover_letter(page, cover_letter_path)

            # 5. Upload resume (if a file input is present)
            await self._upload_resume(page, resume_path)

            # 6. Handle screening questions — log warning, do NOT auto-answer
            has_screening = await self._detect_screening_questions(page)
            if has_screening:
                logger.warning(
                    "Screening questions detected for {} @ {} — "
                    "skipping automated answer, flagging for manual review",
                    job.title,
                    job.company,
                )

            # 7. Click final submit button
            if not await self._click_submit(page):
                await self._capture_screenshot(
                    page, str(app_dir / "submit_failed.png")
                )
                logger.error(
                    "Failed to find/enable submit button for {} @ {}",
                    job.title,
                    job.company,
                )
                # Retry once
                logger.debug("Retrying submit click once...")
                await page.wait_for_timeout(2000)
                if not await self._click_submit(page):
                    await self._capture_screenshot(
                        page, str(app_dir / "submit_failed_retry.png")
                    )
                    return False

            # 8. Wait for success confirmation
            await page.wait_for_timeout(3000)
            await self._human_delay(page)

            success = await self._verify_success(page)

            # 9. Screenshot as evidence
            await self._capture_screenshot(
                page, str(app_dir / "screenshot.png")
            )

            if success:
                logger.success(
                    "Application submitted: {} @ {}", job.title, job.company
                )
            else:
                logger.warning(
                    "Submission verification ambiguous for {} @ {}",
                    job.title,
                    job.company,
                )

            return success

        except Exception as exc:
            await self._capture_screenshot(page, str(app_dir / "error.png"))
            logger.error(
                "Application failed for {} @ {}: {}",
                job.title,
                job.company,
                exc,
            )
            return False

    # ------------------------------------------------------------------
    # Individual action helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _click_apply_now(page: Page) -> bool:
        """Try multiple strategies to find and click the Apply Now button.

        Returns ``True`` if the button was found and clicked.
        """
        selectors = [
            # Text-based
            "button:has-text('Apply Now')",
            "button:has-text('Apply now')",
            "a:has-text('Apply Now')",
            "a:has-text('Apply now')",
            # Class-based
            "[class*='apply_button']",
            "[class*='apply-btn']",
            "[class*='apply_now']",
            "[class*='apply-now']",
            "button[type='submit']:has-text('Apply')",
            # Internshala-specific
            "#apply_button",
            ".apply_button",
            "button.apply",
        ]

        for selector in selectors:
            try:
                btn = await page.wait_for_selector(selector, timeout=5000)
                if btn is not None:
                    await _random_scroll_to(page, btn)
                    await btn.click()
                    logger.debug(f"Clicked Apply Now via selector: {selector}")
                    return True
            except Exception:
                continue

        return False

    @staticmethod
    async def _fill_cover_letter(page: Page, cover_letter_path: str) -> None:
        """Read cover letter text and fill into a textarea if present."""
        cl_path = Path(cover_letter_path)
        if not cl_path.exists():
            logger.warning(f"Cover letter file not found: {cover_letter_path}")
            return

        text = cl_path.read_text(encoding="utf-8").strip()
        if not text:
            return

        selectors = [
            "textarea[name*='cover']",
            "textarea[placeholder*='cover']",
            "textarea[placeholder*='Cover']",
            "textarea#cover_letter",
            "textarea.cover_letter",
            "textarea[name*='message']",
            "textarea[placeholder*='message']",
            # Last-resort: the first visible textarea
            "textarea",
        ]

        for selector in selectors:
            try:
                textarea = await page.wait_for_selector(selector, timeout=3000)
                if textarea is not None and await textarea.is_visible():
                    await _random_scroll_to(page, textarea)
                    await textarea.click()
                    await page.wait_for_timeout(500)
                    await textarea.fill(text)
                    logger.debug(f"Filled cover letter via selector: {selector}")
                    return
            except Exception:
                continue

        logger.debug("No cover letter textarea found — skipping")

    @staticmethod
    async def _upload_resume(page: Page, resume_path: str) -> None:
        """Upload resume PDF if a file input is present.

        If *resume_path* is empty or the file does not exist, this is a
        silent no-op.
        """
        if not resume_path:
            return

        r_path = Path(resume_path)
        if not r_path.exists():
            logger.warning(f"Resume file not found: {resume_path}")
            return

        # Accept both .pdf and .docx
        selectors = [
            "input[type='file'][accept*='pdf']",
            "input[type='file'][accept*='doc']",
            "input[type='file'][accept*='resume']",
            "input[type='file']",
        ]

        for selector in selectors:
            try:
                file_input = await page.wait_for_selector(selector, timeout=3000)
                if file_input is not None:
                    await file_input.set_input_files(str(r_path))
                    logger.debug(f"Uploaded resume via selector: {selector}")
                    return
            except Exception:
                continue

        logger.debug("No file upload input found — resume upload may not be required")

    @staticmethod
    async def _detect_screening_questions(page: Page) -> bool:
        """Return ``True`` if screening/quiz questions are present.

        Checks for ``<select>``, radio buttons, checkboxes, or elements
        with screening-related class names.  These indicate the
        application has custom questions that cannot be auto-answered
        safely.
        """
        indicators = [
            "select",
            "input[type='radio']",
            "input[type='checkbox']",
            "[class*='screening']",
            "[class*='quiz']",
            "[class*='question']",
        ]

        for selector in indicators:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    logger.debug(
                        f"Screening indicator '{selector}' found "
                        f"({len(elements)} element(s))"
                    )
                    return True
            except Exception:
                continue

        return False

    @staticmethod
    async def _click_submit(page: Page) -> bool:
        """Find and click the final submit / send button.

        Returns ``True`` if the button was found, enabled, and clicked.
        """
        selectors = [
            "button[type='submit']:has-text('Submit')",
            "button[type='submit']:has-text('Send')",
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button:has-text('Send Application')",
            "#submit_application",
            ".submit_application",
            "button.submit",
            "input[type='submit']",
            # Last-resort
            "button[type='submit']",
        ]

        # Try once, then retry after a brief pause
        for attempt in range(2):
            for selector in selectors:
                try:
                    btn = await page.wait_for_selector(
                        selector, timeout=5000 if attempt == 0 else 8000
                    )
                    if btn is not None and await btn.is_enabled():
                        await _random_scroll_to(page, btn)
                        await btn.click()
                        logger.debug(f"Clicked submit via selector: {selector}")
                        return True
                except Exception:
                    continue

            if attempt == 0:
                logger.debug("First submit click attempt failed — retrying once")
                await page.wait_for_timeout(2000)

        return False

    @staticmethod
    async def _capture_screenshot(page: Page, path: str) -> None:
        """Capture a full-page screenshot.

        Best-effort; failures are logged at debug level.
        """
        try:
            await page.screenshot(path=path, full_page=True)
            logger.debug(f"Screenshot saved: {path}")
        except Exception as exc:
            logger.debug(f"Failed to capture screenshot: {exc}")

    @staticmethod
    async def _verify_success(page: Page) -> bool:
        """Check for success indicators after submission.

        Looks for visible success text, confirmation class names, or a
        URL that contains success markers.
        """
        success_selectors = [
            "text=Application submitted",
            "text=Successfully applied",
            "text=Application sent",
            "text=Applied successfully",
            "text=Congratulations",
            "[class*='success']",
            "[class*='confirmation']",
            ".application-success",
            ".alert-success",
        ]

        for selector in success_selectors:
            try:
                el = await page.wait_for_selector(selector, timeout=5000)
                if el is not None and await el.is_visible():
                    logger.debug(f"Success indicator found: {selector}")
                    return True
            except Exception:
                continue

        # Fallback: URL-based check
        current_url = page.url.lower()
        if "success" in current_url or "submitted" in current_url:
            logger.debug("Success inferred from URL: {page.url}")
            return True

        return False

    # ------------------------------------------------------------------
    # Human-like behaviour helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _human_delay(page: Page) -> None:
        """Wait a random human-like delay (2-5 seconds)."""
        ms = random.randint(MIN_HUMAN_DELAY_MS, MAX_HUMAN_DELAY_MS)
        await page.wait_for_timeout(ms)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_limits(self) -> None:
        """Raise :class:`RuntimeError` if limits would be exceeded."""
        if self._app_count >= MAX_APPLICATIONS_PER_SESSION:
            raise RuntimeError(
                f"Per-session application limit ({MAX_APPLICATIONS_PER_SESSION}) "
                f"reached.  Start a new session to continue."
            )

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _record_application(job: JobListing) -> None:
        """Update (or insert) the Application record in the database.

        Sets status to ``"submitted"`` and records the submission
        timestamp.  Failures are logged but do not raise.
        """
        if job.id is None:
            logger.warning("Cannot record application: job.id is None")
            return

        try:
            async with get_session() as session:
                from sqlalchemy import select

                result = await session.execute(
                    select(ORMApplication).where(ORMApplication.job_id == job.id)
                )
                app = result.scalar_one_or_none()

                now = datetime.now(datetime.UTC).replace(tzinfo=None)

                if app is None:
                    session.add(
                        ORMApplication(
                            job_id=job.id,
                            status="submitted",
                            portal_submitted=True,
                            portal_submitted_at=now,
                        )
                    )
                    logger.debug(f"Created application record for job {job.id}")
                else:
                    app.status = "submitted"
                    app.portal_submitted = True
                    app.portal_submitted_at = now
                    logger.debug(f"Updated application record for job {job.id}")
        except Exception as exc:
            logger.warning(f"Failed to record application in DB: {exc}")

    @staticmethod
    def _resolve_default_resume() -> str:
        """Try to find a default resume PDF in the project directory.

        Returns an empty string if nothing is found.
        """
        cwd = Path.cwd()
        candidates = [
            cwd / "profile" / "resume.pdf",
            cwd / "resume.pdf",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        logger.warning("No default resume found — resume upload will be skipped")
        return ""


# ---------------------------------------------------------------------------
# Module-level helpers (not part of the class, but shared)
# ---------------------------------------------------------------------------

async def _random_scroll_to(page: Page, element: Any) -> None:
    """Scroll to *element* with a slight random offset and mouse movement.

    Best-effort; failures are silently ignored.
    """
    try:
        box = await element.bounding_box()
        if box is None:
            return

        target_y = box["y"] + random.uniform(0, box["height"] * 0.5)

        # Reset mouse position
        await page.mouse.move(0, 0)
        await page.wait_for_timeout(random.randint(200, 600))

        # Scroll smoothly to just above the element
        await page.evaluate(
            f"window.scrollTo({{top: {target_y - 100}, behavior: 'smooth'}})"
        )
        await page.wait_for_timeout(random.randint(500, 1200))

        # Move mouse towards the element
        x = box["x"] + box["width"] / 2
        await page.mouse.move(x, target_y)
        await page.wait_for_timeout(random.randint(100, 300))

    except Exception:
        pass


__all__ = ["InternshalaSubmitter"]
