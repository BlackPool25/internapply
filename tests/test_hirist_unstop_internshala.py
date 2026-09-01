import json
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

# --- Hirist parses ---

@pytest.mark.asyncio
async def test_hirist_parses():
    from backend.app.discovery.hirist import HiristDiscovery
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jobs": [{"id": "123", "title": "DevOps Intern", "company": "Acme", "location": "Bangalore", "description": "k8s", "lpa": "5 LPA", "postedDate": "2024-01-01", "url": "https://hirist.tech/j/123"}]}
    mock_resp.headers = {}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    d = HiristDiscovery(client=mock_client)
    jobs = await d.search()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "DevOps Intern"
    assert len(jobs[0]["canonical_id"]) == 64
    assert jobs[0]["source_ats"] == "hirist"
    # ensure gladiator url
    assert mock_client.post.call_args[0][0] == "https://gladiator.hirist.tech/job/search"


@pytest.mark.asyncio
async def test_unstop_correct_url():
    from backend.app.discovery.unstop import UnstopDiscovery, UNSTOP_URL
    assert UNSTOP_URL == "https://unstop.com/api/public/opportunity/search-result"
    assert "api.unstop.com" not in UNSTOP_URL
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "u1", "title": "DevOps Challenge", "organisation": "UnstopCo", "location": "Remote", "description": "desc", "stipend": "10k"}]}
    mock_resp.headers = {}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    d = UnstopDiscovery(client=mock_client)
    jobs = await d.search()
    assert len(jobs) == 1
    assert jobs[0]["source_ats"] == "unstop"
    called_url = mock_client.get.call_args[0][0]
    assert called_url == UNSTOP_URL
    params = mock_client.get.call_args[1].get("params", {})
    assert params.get("opportunity") == "all"
    assert params.get("per_page") == 50
    assert params.get("searchTerm") == "devops"
    assert "oppstatus" not in str(mock_client.get.call_args)


@pytest.mark.asyncio
async def test_internshala_fragment():
    from backend.app.discovery.internshala_xhr import InternshalaXhrDiscovery
    html = '<div class="individual_internship"><a href="/internship/detail/test-123"><h3>Python Intern</h3></a><div class="company_name">TestCo</div><span class="stipend">₹ 5000 /month</span><a class="location_link">Bangalore</a></div>'
    payload = {"html": html}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload
    mock_resp.text = json.dumps(payload)
    mock_resp.headers = {}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    d = InternshalaXhrDiscovery(client=mock_client)
    jobs = await d.search()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Python Intern"
    assert jobs[0]["source_ats"] == "internshala"
    # verify XHR headers
    called_headers = mock_client.get.call_args[1].get("headers", {})
    assert called_headers.get("X-Requested-With") == "XMLHttpRequest"


@pytest.mark.asyncio
async def test_hirist_429_retry():
    from backend.app.discovery.hirist import HiristDiscovery
    r429 = MagicMock()
    r429.status_code = 429
    r429.headers = {"Retry-After": "0"}
    r200 = MagicMock()
    r200.status_code = 200
    r200.json.return_value = {"jobs": [{"id": "1", "title": "A", "company": "C", "location": "Bangalore"}]}
    r200.headers = {}
    mock_client = AsyncMock()
    mock_client.post.side_effect = [r429, r200]
    d = HiristDiscovery(client=mock_client)
    jobs = await d.search()
    assert len(jobs) == 1
    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_unstop_old_url_404():
    from backend.app.discovery.unstop import UnstopDiscovery
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.headers = {}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    d = UnstopDiscovery(client=mock_client)
    jobs = await d.search()
    assert jobs == []  # no exception
