from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _df(rows):
    import pandas as pd

    return pd.DataFrame(rows)


@pytest.mark.asyncio
async def test_linkedin_parses():
    from backend.app.discovery.jobspy_linkedin import JobSpyLinkedInDiscovery

    linkedin_rows = [{"title": "DevOps Intern", "company": "Acme", "location": "Bangalore", "description": "k8s docker", "job_url": "https://linkedin.com/jobs/1", "site": "linkedin"}]
    naukri_rows = [{"title": "Backend Intern", "company": "TCS", "location": "Bangalore", "description": "python", "job_url": "https://naukri.com/job/1", "site": "naukri"}]
    indeed_rows = [{"title": "SRE Intern", "company": "Wipro", "location": "Bangalore", "description": "infra", "job_url": "https://indeed.com/viewjob?jk=1", "site": "indeed"}]

    def fake_scrape(**kwargs):
        site = kwargs.get("site_name", [""])[0]
        if site == "linkedin":
            return _df(linkedin_rows)
        if site == "naukri":
            return _df(naukri_rows)
        if site == "indeed":
            return _df(indeed_rows)
        return _df([])

    with patch("jobspy.scrape_jobs", side_effect=fake_scrape):
        disc = JobSpyLinkedInDiscovery()
        disc._jobspy_available = True
        jobs = await disc.search(search_term="DevOps intern", location="Bangalore", hours_old=24, results_wanted=20)
        # assert at least linkedin parsed
        li = [j for j in jobs if j["source_ats"] == "linkedin"]
        assert len(li) == 1
        assert li[0]["title"] == "DevOps Intern"
        assert len(li[0]["canonical_id"]) == 64
        assert all(c in "0123456789abcdef" for c in li[0]["canonical_id"])
        # ensure naukri/indeed also present — whole run not failed
        assert any(j["source_ats"] == "naukri" for j in jobs)


@pytest.mark.asyncio
async def test_indeed_no_limit():
    from backend.app.discovery.jobspy_linkedin import JobSpyLinkedInDiscovery

    indeed_rows = [{"title": f"SRE Intern {i}", "company": "Wipro", "location": "Bangalore", "description": "infra", "job_url": f"https://indeed.com/viewjob?jk={i}", "site": "indeed"} for i in range(20)]

    def fake_scrape(**kwargs):
        site = kwargs.get("site_name", [""])[0]
        if site == "indeed":
            return _df(indeed_rows)
        return _df([])

    with patch("jobspy.scrape_jobs", side_effect=fake_scrape):
        disc = JobSpyLinkedInDiscovery()
        disc._jobspy_available = True
        jobs = await disc.search(search_term="DevOps intern", location="Bangalore", hours_old=24, results_wanted=20, country_indeed="India")
        indeed = [j for j in jobs if j["source_ats"] == "indeed"]
        assert len(indeed) == 20


@pytest.mark.asyncio
async def test_999_circuit_open():
    from backend.app.discovery import jobspy_linkedin as mod

    mod._breaker.clear()

    naukri_rows = [{"title": "Backend Intern", "company": "TCS", "location": "Bangalore", "description": "python", "job_url": "https://naukri.com/job/9", "site": "naukri"}]

    def fake_scrape(**kwargs):
        site = kwargs.get("site_name", [""])[0]
        if site == "linkedin":
            raise Exception("HTTP 999 LinkedIn block")
        if site == "naukri":
            return _df(naukri_rows)
        if site == "indeed":
            return _df([])
        return _df([])

    # ensure no WREQ fallback
    with patch.dict("os.environ", {}, clear=False):
        if "WREQ_SIDECAR_URL" in __import__("os").environ:
            del __import__("os").environ["WREQ_SIDECAR_URL"]
        with patch("jobspy.scrape_jobs", side_effect=fake_scrape):
            disc = mod.JobSpyLinkedInDiscovery()
            disc._jobspy_available = True
            jobs = await disc.search(search_term="DevOps intern", location="Bangalore", hours_old=24, results_wanted=20)
            # 999 must not raise — returns partial naukri results
            assert isinstance(jobs, list)
            assert any(j["source_ats"] == "naukri" for j in jobs)
            assert not any(j["source_ats"] == "linkedin" for j in jobs)
            # breaker SETNX EX 60 — in-memory breaker open
            assert mod.BREAKER_KEY in mod._breaker
            import time

            assert mod._breaker[mod.BREAKER_KEY] > time.time()
            # second call should skip linkedin entirely (breaker open) without calling scrape for linkedin
            call_sites: list[str] = []

            def fake_scrape2(**kwargs):
                site = kwargs.get("site_name", [""])[0]
                call_sites.append(site)
                if site == "naukri":
                    return _df(naukri_rows)
                return _df([])

            with patch("jobspy.scrape_jobs", side_effect=fake_scrape2):
                jobs2 = await disc.search(search_term="DevOps intern", location="Bangalore")
                assert "linkedin" not in call_sites
                assert any(j["source_ats"] == "naukri" for j in jobs2)

    mod._breaker.clear()
