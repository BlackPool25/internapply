import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


def _arbeitnow_payload(n, loc="Remote"):
    data = []
    for i in range(n):
        data.append({
            "slug": f"job-{i}",
            "title": f"Backend Intern {i}",
            "company_name": f"Co{i}",
            "location": loc,
            "description": f"desc {i}",
            "url": f"https://www.arbeitnow.com/jobs/job-{i}",
            "created_at": "2024-01-01",
        })
    return {"data": data}


def _themuse_payload(n, loc="Remote, US"):
    results = []
    for i in range(n):
        results.append({
            "id": i,
            "name": f"Muse Job {i}",
            "company": {"name": f"MuseCo{i}"},
            "locations": [{"name": loc}],
            "contents": f"muse desc {i}",
            "refs": {"landing_page": f"https://themuse.com/jobs/{i}"},
        })
    return {"results": results, "page": 1, "page_count": 5}


def _remotive_payload(n, loc="Remote"):
    jobs = []
    for i in range(n):
        jobs.append({
            "id": i,
            "title": f"Remotive Job {i}",
            "company_name": f"RemCo{i}",
            "candidate_required_location": loc,
            "description": f"rem desc {i}",
            "url": f"https://remotive.com/jobs/{i}",
        })
    return {"jobs": jobs}


@pytest.mark.asyncio
async def test_arbeitnow_paginated():
    from backend.app.discovery.free_apis import FreeAPIsDiscovery

    # page1 20 jobs, page2 [] → loop stops
    p1 = MagicMock()
    p1.status_code = 200
    p1.json.return_value = _arbeitnow_payload(20, loc="Remote")
    p1.headers = {}
    p2 = MagicMock()
    p2.status_code = 200
    p2.json.return_value = _arbeitnow_payload(0)
    p2.headers = {}

    # Need to handle also other sources returning empty to isolate arbeitnow
    # Mock client will be called for arbeitnow pages + other sources; use side_effect function
    async def _get(url, **kwargs):
        if "arbeitnow" in url:
            if "page=1" in url:
                return p1
            return p2
        # other sources: return empty 200
        r = MagicMock()
        r.status_code = 200
        r.headers = {}
        if "remotive" in url:
            r.json.return_value = {"jobs": []}
        elif "themuse" in url:
            r.json.return_value = {"results": []}
        elif "jobicy" in url:
            r.json.return_value = {"jobs": []}
        else:
            r.json.return_value = {}
        return r

    mock_client = AsyncMock()
    mock_client.get.side_effect = _get

    d = FreeAPIsDiscovery(client=mock_client)
    jobs = await d._fetch_arbeitnow(mock_client)
    # raw jobs before filter (Remote passes filter in search but _fetch returns raw)
    assert len(jobs) == 20
    # verify pagination stopped after page2 (called at least 2 arbeitnow urls)
    arbeitnow_calls = [c for c in mock_client.get.call_args_list if "arbeitnow" in str(c)]
    assert len(arbeitnow_calls) == 2
    # search() filtering should keep them (Remote)
    # test via search filtering
    mock_client.get.reset_mock()
    mock_client.get.side_effect = _get
    d2 = FreeAPIsDiscovery(client=mock_client)
    all_jobs = await d2.search()
    # arbeitnow jobs pass filter (Remote) so after should be 20
    assert len(all_jobs) == 20
    assert all(j["source_ats"] == "arbeitnow" for j in all_jobs)
    # loop stops after empty
    assert len([c for c in mock_client.get.call_args_list if "arbeitnow" in str(c)]) == 2


@pytest.mark.asyncio
async def test_themuse_429_retry_after():
    from backend.app.discovery.free_apis import FreeAPIsDiscovery

    r429 = MagicMock()
    r429.status_code = 429
    r429.headers = {"Retry-After": "5"}
    r200 = MagicMock()
    r200.status_code = 200
    r200.headers = {}
    r200.json.return_value = _themuse_payload(2, loc="Bangalore")
    # for themuse page1: 429 then 200; other pages return empty
    empty = MagicMock()
    empty.status_code = 200
    empty.headers = {}
    empty.json.return_value = {"results": []}

    mock_client = AsyncMock()
    # First call 429, second 200, then empty for next pages / other sources
    calls = []

    async def _get(url, **kwargs):
        calls.append(url)
        if "themuse" in url and len([c for c in calls if "themuse" in c]) == 1:
            return r429
        if "themuse" in url and len([c for c in calls if "themuse" in c]) == 2:
            return r200
        if "themuse" in url:
            return empty
        # other sources
        r = MagicMock()
        r.status_code = 200
        r.headers = {}
        r.json.return_value = {"jobs": [], "data": [], "results": []}
        # handle different shapes
        if "arbeitnow" in url:
            r.json.return_value = {"data": []}
        elif "remotive" in url:
            r.json.return_value = {"jobs": []}
        elif "jobicy" in url:
            r.json.return_value = {"jobs": []}
        return r

    mock_client.get.side_effect = _get

    with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
        d = FreeAPIsDiscovery(client=mock_client)
        jobs = await d._fetch_themuse(mock_client)
        # should have retried and got 2 jobs
        assert len(jobs) == 2
        # sleep should have been called with clamped Retry-After 5
        assert mock_sleep.call_count >= 1
        # find call with 5.0
        sleep_vals = [c.args[0] for c in mock_sleep.call_args_list if c.args]
        assert any(abs(v - 5.0) < 0.01 for v in sleep_vals)
    # also verify breaker was attempted (best-effort, no crash)
    assert len([c for c in calls if "themuse" in c]) >= 2


@pytest.mark.asyncio
async def test_remotive_once_per_run():
    from backend.app.discovery.free_apis import FreeAPIsDiscovery

    payload = _remotive_payload(3, loc="Remote")
    r200 = MagicMock()
    r200.status_code = 200
    r200.headers = {}
    r200.json.return_value = payload

    mock_client = AsyncMock()
    mock_client.get.return_value = r200

    d = FreeAPIsDiscovery(client=mock_client)
    jobs1 = await d._fetch_remotive(mock_client)
    assert len(jobs1) == 3
    assert mock_client.get.call_count == 1
    # second call should be no-op due to _remotive_fetched flag
    jobs2 = await d._fetch_remotive(mock_client)
    assert jobs2 == []
    assert mock_client.get.call_count == 1  # still 1, not 2

    # also via search() — second search should not refetch remotive
    mock_client.get.reset_mock()
    mock_client.get.return_value = r200
    d2 = FreeAPIsDiscovery(client=mock_client)
    # mock other sources to avoid extra calls counting toward remotive check
    # Patch _fetch_arbeitnow etc to empty to isolate remotive count
    with patch.object(d2, "_fetch_arbeitnow", new=AsyncMock(return_value=[])), \
         patch.object(d2, "_fetch_themuse", new=AsyncMock(return_value=[])), \
         patch.object(d2, "_fetch_jobicy", new=AsyncMock(return_value=[])):
        await d2.search()
        first_count = mock_client.get.call_count
        assert first_count == 1
        await d2.search()
        # second search should not call remotive again (flag persists)
        assert mock_client.get.call_count == 1
