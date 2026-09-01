"""hash_utils — canonical dedup for internship discovery.

Ponytail ladder: stdlib hashlib.sha256 only, no new deps. 64 hex (sha256), not 128.
"""

from __future__ import annotations

import hashlib
import os
import re

# volatile patterns: dates, view counts, csrf-like hex tokens
_VOLATILE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d+\s+views|[0-9a-f]{32}", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
_PERCENT_RE = re.compile(r"(\d+)\s*%")
_PERCENT_WORD_RE = re.compile(r"(\d+)\s+percent", re.IGNORECASE)


def _get_salt() -> str:
    # lazy: try config, else env, else default — never File.open at import
    for mod in ("internapply.config", "backend.app.config"):
        try:
            m = __import__(mod, fromlist=["get_config", "settings", "HASH_SALT"])
            if hasattr(m, "get_config"):
                try:
                    return str(m.get_config().HASH_SALT)
                except Exception:
                    pass
            if hasattr(m, "settings"):
                try:
                    return str(getattr(m.settings, "HASH_SALT", "internapply-v1"))
                except Exception:
                    pass
            if hasattr(m, "HASH_SALT"):
                return str(getattr(m, "HASH_SALT"))
        except Exception:
            continue
    return os.getenv("HASH_SALT", "internapply-v1")


def _strip_html(text: str) -> str:
    if "<" in text and ">" in text:
        try:
            from bs4 import BeautifulSoup

            return BeautifulSoup(text, "html.parser").get_text(separator=" ")
        except Exception:
            return re.sub(r"<[^>]+>", " ", text)
    return text


def _normalize_percent(text: str) -> str:
    # 40% == 40 percent canonical form "40 percent"
    text = _PERCENT_RE.sub(r"\1 percent", text)
    # collapse "40  percent" variants
    text = _PERCENT_WORD_RE.sub(lambda m: f"{m.group(1)} percent", text)
    return text


def _normalize(text: str) -> str:
    text = _strip_html(text)
    text = text.lower()
    text = _normalize_percent(text)
    text = _VOLATILE_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def canonical_id(company: str, title: str, location: str, source_job_id_or_url: str) -> str:
    """64 hex sha256 of salt+normalized lower fields."""
    salt = _get_salt()
    parts = [
        salt,
        (company or "").strip().lower(),
        (title or "").strip().lower(),
        (location or "").strip().lower(),
        (source_job_id_or_url or "").strip().lower(),
    ]
    raw = "".join(parts).encode()
    return hashlib.sha256(raw).hexdigest()  # 64 hex


def normalize_metric(s: str) -> str:
    """Normalize metric strings: 40% == 40 percent, lower, collapsed."""
    return _normalize(s or "")


def jd_hash(text_or_fields: str | dict | list | tuple = "", *extra: str) -> str:
    """sha256 of normalized canonical JD — volatile stripped, percent synonyms unified.

    Accepts single text string (may contain HTML) or multiple fields / dict.
    """
    if isinstance(text_or_fields, dict):
        # canonical fields: title+company+location+description_text etc
        keys = ("title", "company", "location", "description", "description_text", "stipend_raw", "stipend", "posted_date")
        parts = [str(text_or_fields.get(k, "")) for k in keys if text_or_fields.get(k)]
        if extra:
            parts.extend(str(x) for x in extra)
        text = " ".join(parts)
    elif isinstance(text_or_fields, (list, tuple)):
        parts = [str(x) for x in text_or_fields] + [str(x) for x in extra]
        text = " ".join(parts)
    else:
        text = str(text_or_fields or "")
        if extra:
            text = " ".join([text] + [str(x) for x in extra])
    normalized = _normalize(text)
    return hashlib.sha256(normalized.encode()).hexdigest()


def simhash64(text: str) -> int:
    """Pure-python 64-bit simhash; Hamming <=3 means near-dup (url+title only)."""
    tokens = _normalize(text or "").split()
    if not tokens:
        return 0
    v = [0] * 64
    for tok in tokens:
        # 64-bit token hash via sha256 first 16 hex chars
        h = int(hashlib.md5(tok.encode()).hexdigest()[:16], 16)
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    fp = 0
    for i in range(64):
        if v[i] > 0:
            fp |= 1 << i
    return fp


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def etag_from_response(headers: dict, body: bytes | str | None = None) -> str | None:
    """Advisory only — prefer ETag header else hash body."""
    if not headers:
        headers = {}
    # case-insensitive lookup
    for k, v in headers.items():
        if k.lower() == "etag" and v:
            return str(v)
    if body is not None:
        b = body.encode() if isinstance(body, str) else body
        return hashlib.sha256(b).hexdigest()[:32]
    return None


def diff_change_log(old: str | dict, new: str | dict) -> dict:
    """Diff excluding volatile — empty dict means no meaningful change."""
    oh = jd_hash(old) if isinstance(old, (str, dict, list, tuple)) else jd_hash(str(old))
    nh = jd_hash(new) if isinstance(new, (str, dict, list, tuple)) else jd_hash(str(new))
    if oh == nh:
        return {}
    return {"old_hash": oh, "new_hash": nh, "changed": True}
