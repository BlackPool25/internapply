"""Gmail API sender with secure token storage for InternApply cold emails.

Usage::

    from internapply.outreach.sender import GmailSender

    gmail = GmailSender()
    await gmail.authenticate()
    await gmail.send_email(
        to="hiring@example.com",
        subject="Application for Backend Intern",
        body="...",
    )
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from datetime import UTC, datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, ClassVar

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from loguru import logger

from internapply.config import get_config

__all__ = ["GmailSender"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCOPE = "https://www.googleapis.com/auth/gmail.send"
_ENCRYPTED_TOKEN_NAME = "gmail_token.enc"
_RATE_COUNTER_NAME = "gmail_send_count.json"
_MAX_SENDS_PER_DAY = 20
_WARN_THRESHOLD = 15


# ---------------------------------------------------------------------------
# GmailSender
# ---------------------------------------------------------------------------


class GmailSender:
    """Send cold emails via the Gmail API with encrypted token storage.

    OAuth scope is limited to ``gmail.send`` only (the narrowest possible).
    The OAuth token is encrypted at rest via ``cryptography.fernet`` using a
    key derived from a machine-specific seed and an optional config passphrase.

    All sends require explicit approval (``--approve`` flag in the CLI) as a
    human-in-the-loop gate.  A daily rate limit of 20 emails is enforced.
    """

    SCOPES: ClassVar[list[str]] = [_SCOPE]

    def __init__(self, sender_email: str | None = None) -> None:
        cfg = get_config()
        self._sender_email: str = sender_email or cfg.GMAIL_SENDER_EMAIL
        self._client_secret_path: str | None = (
            cfg.GMAIL_CLIENT_SECRET_PATH or None
        )
        self._fernet: Fernet | None = None
        self._service: Any | None = None
        self._data_dir: Path = Path("data").resolve()

    # ── Public API ────────────────────────────────────────────────────────

    async def authenticate(self) -> bool:
        """Run the OAuth2 flow and save an encrypted token.

        Opens a browser window for Google account authorisation.  The
        resulting token is encrypted and persisted to ``data/gmail_token.enc``.

        Returns ``True`` if authentication succeeded.
        """
        if not self._client_secret_path:
            logger.error(
                "GMAIL_CLIENT_SECRET_PATH is not configured — "
                "cannot run OAuth2 flow"
            )
            return False

        client_secret = Path(self._client_secret_path)
        if not client_secret.exists():
            logger.error(
                "Client secret file not found: {}",
                self._client_secret_path,
            )
            return False

        if not self._sender_email:
            logger.error(
                "GMAIL_SENDER_EMAIL is not configured — cannot authenticate"
            )
            return False

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secret), self.SCOPES
            )
            # Run the local server OAuth flow (opens browser for user)
            creds = flow.run_local_server(port=0, open_browser=True)
            self._save_token(self._token_to_dict(creds))
            logger.info(
                "OAuth2 authentication complete for {}",
                self._sender_email,
            )
            return True
        except Exception:  # noqa: BLE001
            logger.exception("OAuth2 authentication failed")
            return False

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        from_email: str | None = None,
        dry_run: bool = False,
    ) -> bool:
        """Send an email via the Gmail API.

        Rate-limited to 20 emails per day per Gmail account.  Requires a
        previously-saved OAuth token (see :meth:`authenticate`).

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain-text email body.
            from_email: Sender address.  Defaults to ``GMAIL_SENDER_EMAIL``
                from config.
            dry_run: If ``True``, validate inputs and check rate limit but
                do not actually send.  Returns ``True`` if send would succeed.

        Returns:
            ``True`` if the email was sent (or would have been sent during
            a dry run).
        """
        sender = from_email or self._sender_email
        if not sender:
            logger.error("No sender email configured — cannot send")
            return False

        # ── Rate-limit check ──────────────────────────────────────────────
        current_count = self._get_daily_count()
        if current_count >= _MAX_SENDS_PER_DAY:
            logger.warning(
                "Daily send limit ({}) reached — cannot send to {}",
                _MAX_SENDS_PER_DAY,
                to,
            )
            return False

        if current_count >= _WARN_THRESHOLD:
            logger.warning(
                "Approaching daily send limit: {}/{}",
                current_count + 1,
                _MAX_SENDS_PER_DAY,
            )

        # ── Build the raw RFC 2822 message ────────────────────────────────
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = to
        msg["From"] = sender
        msg["Subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        body_payload: dict[str, str] = {"raw": raw}

        if dry_run:
            logger.info(
                "[DRY RUN] Would send email to {} — subject: {!r}",
                to,
                subject,
            )
            return True

        # ── Send via Gmail API ────────────────────────────────────────────
        service = await self._get_service()
        if service is None:
            return False

        try:
            await asyncio.to_thread(
                service.users()
                .messages()
                .send(userId="me", body=body_payload)
                .execute,
            )
            self._increment_daily_count()
            logger.info("Email sent to {} — subject: {!r}", to, subject)
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send email to {}", to)
            return False

    async def validate_connection(self) -> bool:
        """Test the Gmail API connection by sending a diagnostic to self.

        Returns ``True`` if the diagnostic email was sent successfully.
        """
        if not self._sender_email:
            logger.error(
                "GMAIL_SENDER_EMAIL is not configured — "
                "cannot validate connection",
            )
            return False

        return await self.send_email(
            to=self._sender_email,
            subject="InternApply — Gmail API Connection Test",
            body=(
                "This is an automated diagnostic message from InternApply.\n"
                "If you received this, the Gmail API connection is working.\n\n"
                f"Sent at: {datetime.now(UTC).isoformat()}"
            ),
        )

    # ── Token management ──────────────────────────────────────────────────

    def _get_encrypted_token_path(self) -> Path:
        """Return the path to the encrypted token file.

        The file is stored at ``data/gmail_token.enc`` relative to the
        working directory.
        """
        return self._data_dir / _ENCRYPTED_TOKEN_NAME

    def _encrypt_token(self, token_data: dict) -> bytes:
        """Encrypt a token dict using ``cryptography.fernet``.

        The token is serialized as JSON and encrypted with a key derived
        from the machine ID and optional passphrase (see
        :meth:`_derive_fernet_key`).
        """
        fernet = self._get_fernet()
        payload = json.dumps(token_data, default=str).encode()
        return fernet.encrypt(payload)

    def _decrypt_token(self, encrypted: bytes) -> dict:
        """Decrypt a token using ``cryptography.fernet``.

        Args:
            encrypted: The raw encrypted bytes from the token file.

        Returns:
            The deserialised token dict.

        Raises:
            ``cryptography.fernet.InvalidToken`` if decryption fails
            (wrong key or corrupted data).
        """
        fernet = self._get_fernet()
        payload = fernet.decrypt(encrypted)
        return json.loads(payload.decode("utf-8"))

    # ── Internal helpers ──────────────────────────────────────────────────

    def _save_token(self, token_data: dict) -> None:
        """Encrypt and persist the token to ``data/gmail_token.enc``."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        encrypted = self._encrypt_token(token_data)
        self._get_encrypted_token_path().write_bytes(encrypted)
        logger.debug(
            "Encrypted token saved to {}",
            self._get_encrypted_token_path(),
        )

    def _load_token(self) -> dict | None:
        """Load and decrypt the saved token from disk.

        Returns ``None`` if no token file exists or if decryption fails
        (e.g. wrong machine or corrupted file).
        """
        token_path = self._get_encrypted_token_path()
        if not token_path.exists():
            return None
        try:
            encrypted = token_path.read_bytes()
            return self._decrypt_token(encrypted)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to decrypt token at {}", token_path)
            return None

    @staticmethod
    def _token_to_dict(creds: Any) -> dict:
        """Convert Google ``Credentials`` to a plain dict for serialisation."""
        return {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        }

    def _get_fernet(self) -> Fernet:
        """Return a lazily-initialised :class:`Fernet` instance.

        The key is derived deterministically from a machine-specific seed
        and an optional passphrase set via the ``GMAIL_TOKEN_PASSPHRASE``
        environment variable.
        """
        if self._fernet is not None:
            return self._fernet
        self._fernet = Fernet(self._derive_fernet_key())
        return self._fernet

    @staticmethod
    def _derive_fernet_key() -> bytes:
        """Derive a 32-byte url-safe base64 Fernet key.

        Uses SHA-256 of ``<machine-id>:<passphrase>`` where:

        * **machine-id** is read from ``/etc/machine-id`` (Linux), falling
          back to the machine's MAC address.
        * **passphrase** comes from the ``GMAIL_TOKEN_PASSPHRASE`` environment
          variable (optional — empty string when unset).

        This ensures the token can only be decrypted on the same machine
        (or one with a matching passphrase), providing defence in depth.
        """
        import hashlib

        # Machine-specific seed
        try:
            with open("/etc/machine-id") as f:
                seed = f.read().strip()
        except FileNotFoundError:
            seed = str(uuid.getnode())  # MAC address as fallback

        # Optional passphrase from environment
        passphrase = os.getenv("GMAIL_TOKEN_PASSPHRASE", "")

        material = f"{seed}:{passphrase}".encode()
        digest = hashlib.sha256(material).digest()  # 32 bytes
        return base64.urlsafe_b64encode(digest)

    async def _get_service(self) -> Any | None:
        """Build and return an authenticated Gmail API service.

        Loads the saved encrypted token, refreshes it if expired, and
        returns a ``googleapiclient.discovery.Resource`` for the Gmail
        API v1.

        Returns ``None`` if no token is saved or if token loading fails.
        """
        if self._service is not None:
            return self._service

        token_data = self._load_token()
        if token_data is None:
            logger.error(
                "No saved token found — run ``authenticate()`` first",
            )
            return None

        try:
            creds = Credentials(
                token=token_data["token"],
                refresh_token=token_data.get("refresh_token"),
                token_uri=token_data.get("token_uri"),
                client_id=token_data.get("client_id"),
                client_secret=token_data.get("client_secret"),
                scopes=token_data.get("scopes"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to reconstruct credentials from token")
            return None

        # Refresh the token if it has expired
        if creds.expired and creds.refresh_token:
            try:
                await asyncio.to_thread(creds.refresh, Request())
                self._save_token(self._token_to_dict(creds))
                logger.debug("OAuth token refreshed and saved")
            except Exception:  # noqa: BLE001
                logger.exception("Failed to refresh OAuth token")
                return None

        try:
            service = await asyncio.to_thread(
                build,
                "gmail",
                "v1",
                credentials=creds,
                cache_discovery=False,
            )
            self._service = service
            return service
        except Exception:  # noqa: BLE001
            logger.exception("Failed to build Gmail API service")
            return None

    # ── Rate limiting ─────────────────────────────────────────────────────

    def _get_rate_counter_path(self) -> Path:
        """Return the path to the daily send-counter file."""
        return self._data_dir / _RATE_COUNTER_NAME

    def _get_daily_count(self) -> int:
        """Return the number of emails sent today.

        Reads from the local counter file (``data/gmail_send_count.json``).
        Returns 0 if the file does not exist or the recorded date does not
        match today.
        """
        counter_path = self._get_rate_counter_path()
        if not counter_path.exists():
            return 0

        try:
            data = json.loads(counter_path.read_text(encoding="utf-8"))
            if data.get("date") == datetime.now(UTC).date().isoformat():
                return int(data.get("count", 0))
        except (json.JSONDecodeError, ValueError, OSError):
            pass

        return 0

    def _increment_daily_count(self) -> None:
        """Increment the daily send counter by 1.

        If the counter file records a previous date, it is automatically
        reset before incrementing.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(UTC).date().isoformat()
        current = self._get_daily_count()
        data = {"date": today, "count": current + 1}
        self._get_rate_counter_path().write_text(
            json.dumps(data, indent=2), encoding="utf-8",
        )

    def get_daily_send_count(self) -> int:
        """Return the number of emails sent today.

        This is a public convenience wrapper around the internal counter.
        """
        return self._get_daily_count()

    def get_remaining_quota(self) -> int:
        """Return the number of emails that can still be sent today.

        Computed as ``MAX_SENDS_PER_DAY`` minus today's count (never
        returns below 0).
        """
        return max(0, _MAX_SENDS_PER_DAY - self._get_daily_count())
