"""Playwright browser manager with secure CDP configuration.

Security requirements:
- Random port (NOT hardcoded 9222)
- Bind to 127.0.0.1 only (NOT 0.0.0.0)
- Warn if running on shared/cloud machine
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright


class BrowserManager:
    """Manages Playwright browser instances with secure CDP configuration.

    Two connection modes are available:

    * **CDP** (``connect_cdp``) — launches a real Chrome instance with
      ``--remote-debugging-port=0`` (random port) and
      ``--remote-debugging-address=127.0.0.1`` so that the debug server is
      only reachable from localhost.  A fresh temporary user-data-dir is used
      to avoid profile pollution.

    * **Headless** (``launch_headless``) — uses Playwright's bundled Chromium
      in headless mode, suitable for CI or fully automated environments.

    Sessions (cookies + localStorage) can be persisted via
    ``save_session`` / ``load_session``.
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._chrome_process: subprocess.Popen[str] | None = None
        self._user_data_dir: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect_cdp(self) -> Browser:
        """Connect to an existing Chrome instance via CDP.

        Launches Chrome with ``--remote-debugging-port=0`` (random port)
        and ``--remote-debugging-address=127.0.0.1``, then connects
        Playwright over the CDP protocol.

        Returns the connected :class:`Browser` object.
        """
        self._warn_if_shared_machine()

        self._playwright = await async_playwright().start()

        # Create a temporary user-data directory so we don't pick up a
        # running user profile.
        self._user_data_dir = tempfile.mkdtemp(prefix="chrome-cdp-")

        # Locate a Chrome executable
        chrome_path = self._find_chrome()
        logger.info(f"Launching Chrome from: {chrome_path}")

        args = [
            chrome_path,
            "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={self._user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
        ]

        self._chrome_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Parse the actual CDP port from Chrome's stderr output
        port = self._read_cdp_port(self._chrome_process)
        logger.info(f"Chrome CDP listening on 127.0.0.1:{port}")

        endpoint_url = f"http://127.0.0.1:{port}"
        self._browser = await self._playwright.chromium.connect_over_cdp(endpoint_url)
        logger.info("Connected to Chrome via CDP")

        return self._browser

    async def launch_headless(self) -> Browser:
        """Launch a fresh headless Chromium for CI/automated use.

        Uses Playwright's bundled Chromium in headless mode.  No
        persistent profile or CDP port is exposed — the browser is fully
        managed by Playwright.

        Returns the :class:`Browser` object.
        """
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        logger.info("Launched headless Chromium")
        return self._browser

    async def save_session(self, context: BrowserContext) -> str:
        """Save browser context cookies and localStorage to a JSON file.

        Returns the absolute path to the saved session file.
        """
        state = await context.storage_state()

        apps_dir = Path.cwd() / "applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(apps_dir / "browser_session.json")

        with open(out_path, "w") as f:
            json.dump(state, f, indent=2, default=str)

        logger.info(f"Browser session saved to {out_path}")
        return out_path

    async def load_session(self, path: str) -> dict | None:
        """Load a saved browser session from a JSON file.

        The returned dict is compatible with
        ``context.add_cookies(state["cookies"])`` and can be used to
        restore authentication state.

        Returns ``None`` if the file does not exist or is corrupt.
        """
        p = Path(path)
        if not p.exists():
            logger.warning(f"Session file not found: {path}")
            return None

        try:
            with open(p) as f:
                state: dict = json.load(f)
            logger.info(f"Browser session loaded from {path}")
            return state
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(f"Failed to load session from {path}: {exc}")
            return None

    async def close(self) -> None:
        """Close the browser and release all resources.

        Safe to call multiple times.
        """
        if self._browser:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.debug(f"Ignoring browser close error: {exc}")
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.debug(f"Ignoring playwright stop error: {exc}")
            self._playwright = None

        self._kill_chrome_process()

        if self._user_data_dir and os.path.isdir(self._user_data_dir):
            try:
                shutil.rmtree(self._user_data_dir, ignore_errors=True)
            except Exception as exc:
                logger.debug(f"Ignoring cleanup error for {self._user_data_dir}: {exc}")
            self._user_data_dir = None

        logger.info("Browser resources released")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _warn_if_shared_machine() -> None:
        """Emit a warning if the environment appears to be a shared/cloud VM."""
        suspicious: list[str] = []

        hostname = socket.gethostname().lower()
        cloud_patterns = ["aws", "gcp", "azure", "cloud", "ec2", "vm-", "instance"]
        if any(p in hostname for p in cloud_patterns):
            suspicious.append(f"hostname={hostname!r}")

        cloud_vars = [
            "AWS_EXECUTION_ENV",
            "GOOGLE_CLOUD_PROJECT",
            "AZURE_TENANT_ID",
            "CLOUD_SHELL",
        ]
        for var in cloud_vars:
            if os.environ.get(var):
                suspicious.append(f"${var} is set")

        if suspicious:
            logger.warning(
                "This appears to be a shared or cloud machine (%s). "
                "Chrome CDP exposes a debug port to localhost only, but be "
                "aware that other processes on the same machine could "
                "theoretically connect to it.",
                "; ".join(suspicious),
            )

    @staticmethod
    def _find_chrome() -> str:
        """Locate a Chrome/Chromium executable on the current platform.

        Raises :class:`RuntimeError` if none is found.
        """
        candidates: list[str] = []

        # Linux — common paths
        candidates.extend([
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ])

        # macOS
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])

        for candidate in candidates:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                logger.debug(f"Found Chrome at {candidate}")
                return candidate

        # Fallback: search PATH
        which = (
            shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
            or shutil.which("chrome")
        )
        if which:
            logger.debug(f"Found Chrome on PATH: {which}")
            return which

        raise RuntimeError(
            "Could not find a Chrome/Chromium executable. "
            "Install Google Chrome or Chromium, or ensure it is on your PATH."
        )

    @staticmethod
    def _read_cdp_port(process: subprocess.Popen[str], timeout: float = 15.0) -> int:
        """Read the CDP port from Chrome's stderr output.

        Chrome prints a line like::

            DevTools listening on ws://127.0.0.1:<port>/devtools/browser/<id>

        Raises :class:`RuntimeError` if the port cannot be found within
        *timeout* seconds.
        """
        assert process.stderr is not None
        pattern = re.compile(r"DevTools listening on ws://127\.0\.0\.1:(\d+)/")

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            line = process.stderr.readline()
            if not line:
                ret = process.poll()
                if ret is not None:
                    raise RuntimeError(
                        f"Chrome process exited unexpectedly (return code {ret})"
                    )
                time.sleep(0.05)
                continue

            line = line.strip()
            match = pattern.search(line)
            if match:
                return int(match.group(1))

        raise RuntimeError(
            f"Could not determine CDP port within {timeout:.0f}s "
            f"from Chrome stderr output"
        )

    def _kill_chrome_process(self) -> None:
        """Terminate the Chrome subprocess if it is still running."""
        if self._chrome_process is None:
            return

        proc = self._chrome_process
        self._chrome_process = None

        if proc.poll() is not None:
            logger.debug("Chrome process already exited")
            return

        logger.debug("Terminating Chrome process (pid=%d)", proc.pid)
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Chrome did not exit gracefully — sending SIGKILL")
            proc.kill()
            proc.wait()
        except Exception as exc:
            logger.warning(f"Error while terminating Chrome: {exc}")
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass


__all__ = ["BrowserManager"]
