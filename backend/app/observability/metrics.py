"""Prometheus metrics + structlog JSON for discovery.

Counter(discovery_jobs_total{source,status}) success/failure/skip
Histogram(discovery_latency_seconds, buckets) per source
Gauge(queue_depth)
GET /health/discovery via health_state
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from prometheus_client import Counter, Gauge, Histogram

# structlog JSON logger
logger = structlog.get_logger(__name__)

# prometheus metrics
discovery_jobs_total = Counter(
    "discovery_jobs_total",
    "Total discovery jobs",
    ["source", "status"],
)

discovery_latency_seconds = Histogram(
    "discovery_latency_seconds",
    "Discovery latency",
    ["source"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30),
)

queue_depth = Gauge("queue_depth", "Queue depth")

# health state: source -> {last_run, latency_p50, latencies[], breaker_open, dead_letters}
_health_state: dict[str, dict[str, Any]] = {}


def parse_retry_after(value: str | None) -> float | None:
    """Parse Retry-After: seconds or HTTP-date, clamp max_wait=30. Returns None if missing/invalid."""
    if not value:
        return None
    v = value.strip()
    # try seconds
    try:
        secs = float(v)
        return max(0, min(secs, 30))
    except ValueError:
        pass
    # try HTTP-date
    try:
        import email.utils

        dt = email.utils.parsedate_to_datetime(v)
        if dt is not None:
            now = time.time()
            target = dt.timestamp()
            secs = target - now
            if secs < 0:
                secs = 0
            return max(0, min(secs, 30))
    except Exception:
        pass
    return None


def record_job(source: str, status: str, latency: float) -> None:
    """Record metrics + structlog + health state."""
    try:
        discovery_jobs_total.labels(source=source, status=status).inc()
    except Exception:
        pass
    try:
        discovery_latency_seconds.labels(source=source).observe(latency)
    except Exception:
        pass
    # structlog JSON
    try:
        logger.info("discovery_job", source=source, status=status, latency=latency)
    except Exception:
        pass
    # health state
    entry = _health_state.setdefault(source, {"latencies": [], "last_run": None, "dead_letters": 0})
    entry["last_run"] = time.time()
    entry.setdefault("latencies", []).append(latency)
    # keep last 20 latencies for p50
    if len(entry["latencies"]) > 20:
        entry["latencies"] = entry["latencies"][-20:]
    # compute p50
    lat = sorted(entry["latencies"])
    n = len(lat)
    if n:
        entry["latency_p50"] = lat[n // 2]
    else:
        entry["latency_p50"] = 0.0


def record_dead_letter(source: str) -> None:
    entry = _health_state.setdefault(source, {"latencies": [], "last_run": None, "dead_letters": 0})
    entry["dead_letters"] = entry.get("dead_letters", 0) + 1
    # also increment circuit dead letters list if available
    try:
        from backend.app.discovery.circuit import add_dead_letter

        add_dead_letter(source, url=f"dead:{source}:{time.time()}", status_code=999, error="dead_letter")
    except Exception:
        pass


def get_health_state() -> dict[str, dict[str, Any]]:
    # enrich with breaker_open flag
    try:
        from backend.app.discovery.circuit import CircuitBreaker

        for src, entry in _health_state.items():
            try:
                entry["breaker_open"] = CircuitBreaker.is_open(src)
            except Exception:
                entry["breaker_open"] = False
            # ensure dead_letters count from circuit
            try:
                from backend.app.discovery.circuit import get_dead_letters

                entry["dead_letters"] = len(get_dead_letters(src))
            except Exception:
                pass
    except Exception:
        pass
    return dict(_health_state)


def reset_for_tests() -> None:
    _health_state.clear()
    # reset prometheus counters by clearing? prometheus_client doesn't support reset easily; set to 0 via _metrics
    try:
        discovery_jobs_total.clear()  # type: ignore
    except Exception:
        pass
    try:
        # Histogram clear
        discovery_latency_seconds.clear()  # type: ignore
    except Exception:
        pass
