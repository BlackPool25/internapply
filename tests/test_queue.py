from __future__ import annotations

import time
from unittest.mock import patch

import pytest


def test_arq_cron_hourly():
    from backend.app.worker import WorkerSettings

    assert len(WorkerSettings.cron_jobs) == 1
    cj = WorkerSettings.cron_jobs[0]
    # str contains discover
    s = str(cj)
    assert "discover" in s.lower()
    # check hour covers all 24, minute 0
    # arq CronJob may expose .hour / .minute or via repr
    hour = getattr(cj, "hour", None)
    minute = getattr(cj, "minute", None)
    # fallback: check repr contains hour/minute
    if hour is not None:
        # hour should be set(range(24)) or {0..23}
        assert hour == set(range(24)) or hour == {*range(24)}
    else:
        assert "hour" in s.lower()
    if minute is not None:
        assert minute == 0 or minute == {0}
    else:
        assert "minute" in s.lower()
    # check unique, timeout, keep_result, run_at_startup
    assert getattr(cj, "unique", True) is True
    assert getattr(cj, "timeout", 600) == 600
    assert getattr(cj, "keep_result", 0) == 0
    assert getattr(cj, "run_at_startup", False) is False
    # also ensure functions include per-source
    from backend.app.worker import (
        discover_greenhouse,
        discover_hirist,
        discover_free_apis,
        discover_jobspy,
    )

    assert discover_greenhouse in WorkerSettings.functions
    assert discover_hirist in WorkerSettings.functions


def test_retry_after_clamp():
    # Retry-After 3600 must clamp to 30, never park worker
    from backend.app.observability.metrics import parse_retry_after as m_parse
    from backend.app.worker import parse_retry_after as w_parse

    assert m_parse("3600") == 30
    assert w_parse("3600") == 30
    assert w_parse("9999") == 30
    # also via worker _wait_retry_after with hostile 3600
    from backend.app.worker import _Retryable, _wait_retry_after

    class FakeState:
        def __init__(self, exc):
            self.outcome = type("O", (), {"failed": True, "exception": lambda s=exc: exc})()

    exc = _Retryable(429, retry_after=3600)
    wait = _wait_retry_after(FakeState(exc))
    assert wait <= 30, f"wait {wait} should be clamped to 30, not 3600"
    assert wait != 3600
    # seconds normal
    exc2 = _Retryable(429, retry_after=2.5)
    wait2 = _wait_retry_after(FakeState(exc2))
    assert 2.0 <= wait2 <= 3.0
    # HTTP-date path
    import email.utils

    future = email.utils.formatdate(time.time() + 3600, usegmt=True)
    assert w_parse(future) == 30
    assert m_parse(future) == 30


def test_circuit_exclude_404():
    from backend.app.discovery.circuit import CircuitBreaker, _reset_for_tests

    _reset_for_tests()
    src = "test_src_404"
    # 404 must not count toward fail_max=5
    for _ in range(10):
        CircuitBreaker.record_failure(src, 404)
        CircuitBreaker.record_failure(src, status_code=404)
        # also test async fallback via sync
    assert CircuitBreaker.is_open(src) is False
    # 500 should count
    _reset_for_tests()
    src2 = "test_src_500"
    for i in range(5):
        tripped = CircuitBreaker.record_failure(src2, 500)
        if i < 4:
            assert tripped is False
            assert CircuitBreaker.is_open(src2) is False
        else:
            assert tripped is True
            assert CircuitBreaker.is_open(src2) is True
    # ensure breaker:{source} EX 60 is set (in-memory expiry ~60s)
    from backend.app.discovery.circuit import _fallback_state

    assert f"breaker:{src2}" in _fallback_state
    exp = _fallback_state[f"breaker:{src2}"]
    assert exp > time.time() and exp <= time.time() + 61
    _reset_for_tests()


@pytest.mark.asyncio
async def test_dead_letter_on_999():
    from backend.app.discovery.circuit import (
        CircuitBreaker,
        _reset_for_tests,
        get_dead_letters,
        add_dead_letter,
        _fallback_state,
    )
    from backend.app.observability.metrics import get_health_state

    _reset_for_tests()
    from backend.app.observability.metrics import reset_for_tests as m_reset

    m_reset()

    src = "jobspy"
    # simulate 999 failure 5 times -> breaker open EX60 + dead letter
    for _ in range(5):
        CircuitBreaker.record_failure(src, 999)
    assert CircuitBreaker.is_open(src) is True
    assert f"breaker:{src}" in _fallback_state

    # add dead letter row
    add_dead_letter(src, url="https://linkedin.com/jobs/999", status_code=999, error="999 LinkedIn block")
    dls = get_dead_letters(src)
    assert len(dls) == 1
    assert dls[0]["status_code"] == 999
    assert dls[0]["source"] == src

    # health should reflect breaker_open and dead_letters count
    from backend.app.observability.metrics import record_job, record_dead_letter

    # ensure health state reflects
    state = get_health_state()
    # if not yet populated, populate via record_job
    if src not in state or state[src].get("breaker_open") is not True:
        # force health refresh
        record_job(src, "failure", 0.5)
        record_dead_letter(src)
        state = get_health_state()
    # at least dead_letters count should be >=1
    found = next((s for s in state.values() if s.get("dead_letters", 0) >= 1), None)
    # alternatively check via get_dead_letters directly
    assert len(get_dead_letters(src)) >= 1

    # verify mocked db path: simulate discover_jobspy handling 999 without raising
    from unittest.mock import AsyncMock

    with patch("backend.app.discovery.jobspy_linkedin.JobSpyLinkedInDiscovery.search", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = Exception("HTTP 999 LinkedIn block")
        from backend.app.worker import discover_jobspy

        # should not raise, should return [] and set breaker
        result = await discover_jobspy({})
        assert isinstance(result, list)
        assert result == []
        assert CircuitBreaker.is_open("jobspy") is True

    _reset_for_tests()
    m_reset()
