# InternApply — System Architecture

## Overview

InternApply is an automated internship application system. It discovers paid backend internships (Python/Java, remote/Bangalore) from ATS boards, Hirist, Unstop, Internshala, JobSpy, and free overflow feeds, filters with deterministic hash dedup, saves to Postgres, and tailors resumes on demand via an opencode skill with a verifier gate.

**Tech Stack**: Python 3.12, LangGraph, OpenCode Go (deepseek-v4-flash), Postgres 16 + asyncpg + Alembic, Redis 7 + arq, httpx + tenacity, python-docx

---

## Project Structure

```
~/projects/internapply/
├── internapply/                  # Legacy CLI package (SQLite mirror)
│   ├── config.py                 # Pydantic-settings config from .env (lazy boards)
│   ├── database.py               # Async SQLAlchemy — Postgres primary, SQLite fallback
│   ├── models.py                 # Pydantic v2 data models
│   ├── llm.py                    # OpenCode Go API wrapper (OpenAI-compatible)
│   │
│   ├── discovery/                # Job discovery modules
│   │   ├── ats/                  # Tier0: Greenhouse, Lever, Ashby, SmartRecruiters
│   │   ├── hirist.py             # Tier1: Hirist gladiator.hirist.tech POST
│   │   ├── unstop.py             # Tier1: Unstop corrected API
│   │   ├── internshala_xhr.py    # Tier1: Internshala XHR fragment parser
│   │   ├── free_apis.py          # Tier3 overflow: Arbeitnow/Remotive/TheMuse/Jobicy
│   │   ├── jobspy_linkedin.py    # Tier2: JobSpy Naukri/Indeed + Tier3 LinkedIn overflow
│   │   ├── hash_utils.py         # canonical_id 64, jd_hash, simhash
│   │   └── freelance/            # Freelancer RSS + Internshala freelance XHR
│   │
│   ├── resume/                   # Resume engine
│   │   ├── parser.py             # Parses JS generator → structured JSON
│   │   ├── analyzer.py           # JD skill extraction (LLM + deterministic fallback)
│   │   ├── tailor.py             # LLM resume tailoring + Markdown renderer
│   │   ├── verifier.py           # Deterministic hallucination gate (6 checks, WARN@80)
│   │   ├── scorer.py             # ATS keyword scorer (0-100, deterministic)
│   │   ├── cover_letter.py       # LLM cover letter + humanization
│   │   └── renderer.py           # Professional DOCX resume generator (96.7% parse)
│   │
│   ├── pipeline/                 # Truncated orchestrator (3 nodes)
│   │   ├── state.py              # PipelineState TypedDict
│   │   ├── graph.py              # StateGraph definition (3 nodes: discover→filter→save)
│   │   └── nodes.py              # Pipeline node functions
│   │
│   └── cli/                      # CLI interface
│       ├── main.py               # Typer app entry point
│       ├── resume.py             # Resume management commands
│       ├── discover.py           # Discovery command
│       ├── tailor.py             # Resume tailoring command (skill on-demand)
│       └── doctor.py             # System check command
│
├── backend/app/                  # FastAPI backend (Postgres + arq)
│   ├── worker.py                 # arq worker: hourly discover_all cron + per-source tasks
│   ├── database.py               # Postgres engine pool 10/10 + Alembic
│   ├── discovery/circuit.py      # Circuit breaker (SET NX EX 60) + dead_letters
│   └── observability/metrics.py  # Prometheus: queue depth, breaker, dead letters
│
├── .opencode/skills/resume-tailor/SKILL.md  # On-demand skill: tailor + verifier WARN@80
├── config/boards.json            # Probed working ~100 ATS boards (cursor updated_at|posted_date)
├── docker/docker-compose.yml     # Postgres 16 + Redis 7 + arq worker + FastAPI + Next.js
├── tests/                        # 63+ tests
├── profile/resume.json           # Master resume (canonical source)
└── ARCHITECTURE.md               # This file
```

---

## Pipeline Architecture (Truncated: 3 Nodes)

The pipeline is a truncated 3-node StateGraph with arq queue and Postgres persistence:

```
discover → filter → save → (on-demand skill WARN@80)
```

The previous flow (discover → filter → analyze → tailor → cover_letter → email → apply) is retired. Tailoring, cover letters, and outreach now run only through the on-demand opencode skill `resume-tailor` with verifier WARN at 70-79 and hard 422 after 30 JDs.

### Discover (Tiered)

Discovery fans out across tiers, each with cursor support and per-source handling. All fetch via httpx with tenacity `wait_exponential_jitter(multiplier=0.5, max=30)` and `Retry-After` clamp at 30s.

| Tier | Sources | How it works | Cost/1k | API/Push |
|------|---------|--------------|---------|----------|
| **Tier0 ATS** | Greenhouse, Lever, Ashby, SmartRecruiters | Probed ~100 working boards from 200 candidates; cursor updated_at|posted_date fallback (updated_at preferred, posted_date if missing); concurrency 10, per-ATS rate limit (Greenhouse 1s, Lever 2s) | ₹0 | keyless JSON |
| **Tier1** | Hirist gladiator + Unstop corrected + Internshala XHR fragment | Hirist POST `gladiator.hirist.tech/job/search` with `appId:hirist` header (free JSON, never jobseeker-api); Unstop corrected `api.unstop.com` search; Internshala XHR fragment parser | ₹0 | Hirist free JSON, Unstop free JSON |
| **Tier3 free overflow** | Arbeitnow, Remotive, TheMuse (Jobicy optional) | Paginated 20/page, up to 5 pages per source; Arbeitnow free, Remotive free capped, TheMuse 500/hr anon; EU/US feeds — 90%+ filtered for Bangalore narrow | ₹0 | free APIs capped |
| **Tier2** | JobSpy Naukri/Indeed | JobSpy with proxybroker2 rotation | ₹0 | free scrape |
| **Tier3** | LinkedIn overflow via JobSpy | 999 breaker: first 999 opens breaker `SET NX EX 60`, writes dead_letters, skips; wreq-js fallback via `WREQ_SIDECAR_URL=http://wreq:3000` (optional Node JA3 sidecar) | ₹0 | breaker + wreq-js fallback |

Cursor behavior: each ATS board tracks `cursor` as the last seen `updated_at` value, falling back to `posted_date` when `updated_at` is absent. Next discovery pass requests only jobs where `updated_at > cursor` or `posted_date > cursor`, so the probe stays incremental and avoids re-fetching unchanged listings.

Cost: discovery ₹0/1k (all free tiers) + LLM ₹0-12/mo (skill only, on-demand — batch never calls LLM).

### Filter (Hash Dedup)

Filter runs deterministic dedup before save. No LLM in batch.

| Field | Type | Role |
|-------|------|------|
| `canonical_id` | `VARCHAR(64) UNIQUE` | sha256(salt + lower(company+title+location+source_id)) — 64 hex, primary dedup key |
| `jd_hash` | `VARCHAR(64)` primary | sha256(normalized JD text with volatile stripping) — detects content changes; jd_hash primary for change log |
| `simhash` | `BIGINT` residual | 64-bit simhash of title+url; Hamming <=3 (SIMHASH_THRESHOLD) catches near-dups missed by exact hash |

Flow: exact `canonical_id` match → skip as seen. If `jd_hash` differs for same `canonical_id` → mark `changed` (not `new`) and update `diff_change_log`. Residual `simhash` Hamming check catches near-duplicates with minor title rewrites. Volatile stripping removes dates, view counts, and hex tokens before hashing.

### Save

Save writes to Postgres (`job_listings` table) with `canonical_id 64 UNIQUE` and `jd_hash` index. ETag header stored when present, body hash fallback. Source badges and drift tracking (`new/changed/gone`) computed from hash diffs. On conflict, upsert keeps the newest `jd_hash` and updates `updated_at`.

### On-Demand Skill (resume-tailor WARN@80)

Tailoring is not part of the batch pipeline. The opencode skill at `.opencode/skills/resume-tailor/SKILL.md` runs only when the user invokes it from the dashboard or CLI.

- LLM tailors resume for the selected JD
- Verifier gate runs 6 deterministic checks (project names, skills, dates, metrics, education, cliches)
- Score <80 → verifier WARN yellow for first 30 JDs (70-79 shows warning but allows save), hard 422 after 30 JDs if still below 80
- DOCX renderer produces ATS-optimized output at 96.7% parse rate
- Cache keyed by `jd_hash` so re-tailoring the same JD hits cache

### State (PipelineState)

```python
class PipelineState(TypedDict):
    config: dict              # Snapshot of current config
    jobs: list[dict]          # Job listings being processed
    raw_jobs_count: int
    filtered_jobs_count: int
    current_job_index: int
    seen_canonical_ids: set[str]  # Dedup set for this run
    cursor: dict[str, str]    # Per-source cursor: updated_at|posted_date fallback
    jd_hash: Optional[str]    # Current JD hash for change detection
    canonical_id: Optional[str]  # Current canonical_id 64
    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    run_id: Optional[str]
    dry_run: bool
    stage: str
```

### Key Pipeline Behaviors

- **arq queue**: hourly `discover_all` cron fans per-source tasks; queue depth gauge tracks fanout
- **Circuit breaker**: Redis `SET NX EX 60` per source; 999 on LinkedIn opens breaker for 60s and skips
- **Dead letters**: `dead_letters` table `(source, url) UNIQUE` buffers 429/5xx/999 for retry; `next_retry_at` scheduling
- **Cursor**: `updated_at|posted_date` fallback per board — incremental fetch, never full rescan
- **Hash dedup**: `canonical_id 64 UNIQUE` is the source of truth; `jd_hash primary` for change detection; `simhash` residual for fuzzy matches
- **Verifier WARN**: score 70-79 yellow WARN for first 30 JDs, hard 422 after 30 if still <80
- **Cost**: ₹0/1k discovery + ₹0-12/mo LLM (skill only)

---

## arq Queue + Dead Letter + Metrics

### arq Worker

`backend/app/worker.py` defines `WorkerSettings` with `cron(discover_all, hour={*range(24)}, minute=0)` — hourly fanout across all tiers. Per-source tasks (`discover_greenhouse`, `discover_hirist`, etc.) each wrap discovery with tenacity and circuit breaker. The worker runs as a Docker service (`internapply-worker`) backed by Redis 7.

- Concurrency: semaphore 10 for ATS probing
- Retry: `stop_after_attempt(3)`, `wait_exponential_jitter(multiplier=0.5, max=30)`, clamped `Retry-After` (never 3600 parks worker)
- Skip list: 401/403/404/422 never retry; 429/502/503/504 retry with backoff

### Dead Letter Table

```sql
CREATE TABLE dead_letters (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    status_code INT,
    error TEXT,
    next_retry_at TIMESTAMPTZ,
    UNIQUE (source, url)
);
CREATE INDEX ix_dead_letters_next_retry_at ON dead_letters(next_retry_at);
```

Failed fetches that exhaust retries land in `dead_letters`. The hourly cron retries entries where `next_retry_at <= now()`. 999 from LinkedIn is treated as hostile and dead-lettered immediately with breaker open.

### Metrics (Prometheus)

Exposed via `backend/app/observability/metrics.py`:

| Metric | Type | What it tracks |
|--------|------|----------------|
| `queue_depth` | Gauge | arq fanout depth (0 when idle, ~10 during discover) |
| `circuit_breaker_open{source}` | Gauge | 1 if breaker open for that source |
| `dead_letters_total{source}` | Counter | dead letter inserts per source |
| `discover_latency_p50{source}` | Histogram | per-source fetch latency |

Dashboard KPI `working_boards` shows count of boards with `latency_p50` and `has_updatedAt` probe metadata.

---

## Configuration (.env)

### Required
```
OPENCODE_GO_API_KEY=sk-...        # OpenCode Go subscription API key
OPENCODE_GO_MODEL=deepseek-v4-flash # LLM model
OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1
```

### Infra (Docker)
```
DATABASE_URL=postgresql+asyncpg://internapply:changeme@postgres:5432/internapply # service name postgres not localhost
REDIS_URL=redis://redis:6379/0
HASH_SALT=internapply-v1
SIMHASH_THRESHOLD=3
VERIFIER_MIN_SCORE=80 # WARN yellow 70-79 for first 30 JDs, hard 422 after
WREQ_SIDECAR_URL=http://wreq:3000 # optional Node wreq-js JA3 sidecar for LinkedIn 999 fallback
VOLLNA_RSS_URL= # optional for Upwork webhook
ARBEITNOW_ENABLED=true
HIRIST_ENABLED=true
UNSTOP_ENABLED=true
REMOTIVE_ENABLED=true
THEMUSE_ENABLED=true
```

### Optional — Discovery
```
SEARCH_KEYWORDS=["python","java","backend","software development","full stack"]
SEARCH_LOCATIONS=["Remote","Bangalore"]
MIN_STIPEND_INR=5000
```

### Optional — Email Outreach
```
HUNTER_API_KEY=...                 # Hunter.io (50 free searches/month, X/50 counter, not in batch)
GMAIL_SENDER_EMAIL=...             # Gmail address to send from
GMAIL_CLIENT_SECRET_PATH=...       # Google Cloud OAuth client_secret.json
```

---

## Data Models

### JobListing (Postgres `job_listings`)
Stores discovered jobs. Key fields: title, company, location, stipend_min/max, stipend_raw, skills (JSONB), analysis (JSONB), description, source, url, posted_at, posted_at_date, cursor (updated_at|posted_date fallback), canonical_id `VARCHAR(64) UNIQUE`, jd_hash `VARCHAR(64)` primary index, simhash `BIGINT`, etag, drift (`new/changed/gone`), is_paid, is_remote. Postgres 16 is primary; `internapply/database.py` keeps SQLite only as CLI mirror/offline fallback.

### Application
Tracks application state per job. Fields: job_id, status, tailored_resume_path, cover_letter_path, email_sent, verifier_score, humanization_score.

### Resume
Master resume data. Fields: name, email, phone, location, summary, education (JSONB), skills (JSONB dict by category), projects (JSONB), additional (JSONB). Canonical source: `profile/resume.json`.

### DeadLetter
Buffers failed fetches. Fields: source, url (UNIQUE together), status_code, error, next_retry_at.

---

## CLI Commands

```bash
internapply doctor               # System check (all API keys, files, DB, working ~100 boards)
internapply resume init [file]   # Parse JS generator → profile/resume.json
internapply resume show          # Display current resume
internapply discover             # Find internships (--dry-run, --max-jobs, tiered)
internapply run                  # Truncated pipeline: discover→filter→save (--dry-run)
internapply status               # Dashboard of jobs/applications/emails
# Tailoring is via skill, not CLI batch:
# .opencode/skills/resume-tailor/SKILL.md — on-demand, verifier WARN@80, DOCX 96.7%
```

---

## Tests (63+ tests)

| Test File | Tests | What It Verifies |
|-----------|-------|-----------------|
| test_verifier.py | 12 | Clean resume passes (100), FakeProject detected, date normalization, education mismatch, metrics, cliches; WARN@80 |
| test_scorer.py | 6 | Deterministic scoring, keyword match, format scoring, title match |
| test_pipeline.py | 10 | State initialization, graph topology (3 nodes), error accumulation, truncated flow |
| test_database.py | 8 | Migration V3, canonical_id 64 UNIQUE, jd_hash index, dead_letters unique(source,url) |
| test_probe.py | 5 | Probe gate working >=100, dead threshold, 429 backoff, hirist gladiator ok |
| test_queue.py | 5 | arq cron hourly, dead letter on 999, Retry-After clamp 30 |
| test_config.py | 6 | Defaults, env overrides, list parsing, lazy boards property |
| test_hash_utils.py | 6 | canonical_id 64, jd_hash primary, simhash residual, volatile stripping |

---

## External Dependencies / API Keys

| Service | Cost | Usage | Cost/1k | API/Push | Key In .env |
|---------|------|-------|---------|----------|-------------|
| **Postgres 16** | Free (Docker) | Primary datastore, canonical_id 64 UNIQUE, dead_letters | ₹0 | local | `DATABASE_URL` |
| **Redis 7 + arq** | Free (Docker) | Job queue, circuit breaker, dead letter scheduling | ₹0 | local | `REDIS_URL` |
| **ATS Boards** | Free | Tier0 probed ~100 boards, keyless JSON, cursor updated_at | ₹0 | keyless JSON | — |
| **Hirist gladiator** | Free | `POST gladiator.hirist.tech/job/search` with appId header | ₹0 | free JSON | `HIRIST_ENABLED` |
| **Unstop** | Free | Corrected search API | ₹0 | free JSON | `UNSTOP_ENABLED` |
| **Arbeitnow** | Free | Tier3 free overflow, paginated 20/page | ₹0 | free capped | `ARBEITNOW_ENABLED` |
| **Remotive** | Free | Tier3 free overflow | ₹0 | free capped | `REMOTIVE_ENABLED` |
| **TheMuse** | Free | Tier3 500/hr anon | ₹0 | free capped 500/hr | `THEMUSE_ENABLED` |
| **OpenCode Go** | ₹0-12/mo | Skill only (on-demand tailor), never in batch | ₹0-12/mo | skill | `OPENCODE_GO_API_KEY` |
| **Hunter.io** | Free tier (50/mo) | Email finder, X/50 counter, not in batch | ₹0 | free capped | `HUNTER_API_KEY` |
| **Gmail API** | Free | Send cold emails, encrypted tokens, --approve gate | ₹0 | — | `GMAIL_*` |

---

## How Each Component Works

### ATS Discovery (discovery/ats/)
Probes 200 candidates (Greenhouse/Lever/Ashby/SmartRecruiters) with `httpx.AsyncClient(timeout=10, limits=Limits(max_connections=20))`, semaphore 10, per-ATS rate limits. Cursor tracks `updated_at` with `posted_date` fallback for incremental fetch. Boards with `working` status and `has_updatedAt` flag are kept in `config/boards.json` (working ~100, dead 109, p50 ~327ms).

### Hirist Gladiator (discovery/hirist.py)
`POST https://gladiator.hirist.tech/job/search` with headers `appId:hirist, Referer:https://hirist.tech`. Never `jobseeker-api.hirist.com`. Body `{query, location}`. Returns jobs array with JD and stipend. Free JSON, no key.

### Unstop (discovery/unstop.py)
Corrected `api.unstop.com` search endpoint (not `/search_internships`). Paginated, respects filter params.

### Internshala XHR Fragment (discovery/internshala_xhr.py)
Parses XHR JSON fragments rather than full HTML. Lightweight, no Playwright in discovery.

### Free Overflow (discovery/free_apis.py)
Tier3 paginated 20/page, up to 5 pages per source. Arbeitnow free, Remotive free capped, TheMuse 500/hr anon. EU/US remote feeds — 90%+ filtered for Bangalore narrow. Each source respects `*_ENABLED` flag and `Retry-After` clamp.

### JobSpy LinkedIn Overflow (discovery/jobspy_linkedin.py)
JobSpy for Naukri/Indeed (Tier2) + LinkedIn overflow (Tier3). 999 response triggers breaker `SET NX EX 60`, dead_letter insert, and optional wreq-js fallback via `WREQ_SIDECAR_URL`. Never auto-submits to LinkedIn — external link only.

### Hash Dedup (discovery/hash_utils.py)
Stdlib `hashlib.sha256` only. `canonical_id` 64 hex of salt+lower(company+title+location+source_id). `jd_hash` primary of normalized JD (volatile stripping for dates/views/hex tokens, percent synonym unification). `simhash64` residual with Hamming <=3 (threshold 3) for fuzzy near-dups.

### Resume Tailor Skill (resume/tailor.py + .opencode/skills/resume-tailor/)
LLM prompt with 8 strict rules (no fabrication, student context, reorder only). Verifier gate retries up to 2 times if verifier WARN below 80. First 30 JDs show yellow WARN at 70-79; hard 422 after 30 if still <80. DOCX 96.7% ATS parse rate.

### Verifier Gate (resume/verifier.py)
Fully deterministic — NO LLM calls. 6 checks: project names, skills, dates, metrics, education, cliches. Score = max(0, 100 - violations×20). Verifier WARN at 70-79, hard fail at <70 or after 30 JDs <80.

### arq Worker (backend/app/worker.py)
Hourly `discover_all` cron via `arq.cron(hour={*range(24)}, minute=0)`. Per-source tenacity, circuit breaker, dead letters. Prometheus metrics for queue depth, breaker state, dead letters.

---

## Key Design Decisions (with Research Basis)

| Decision | Research | Implementation |
|----------|----------|---------------|
| **Truncated 3-node pipeline** | Batch should never call LLM; skill is on-demand | discover→filter→save, skill WARN@80 |
| **Tiered discovery** | No single source covers all roles | Tier0 ATS ~100 + Tier1 Hirist/Unstop/Internshala + Tier2 JobSpy + Tier3 free overflow |
| **Hash 64 not 128** | sha256 64 hex is sufficient, 128 is waste | canonical_id VARCHAR(64) UNIQUE, jd_hash primary 64 |
| **Cursor updated_at\|posted_date fallback** | ATS boards expose updated_at inconsistently | Prefer updated_at, fallback to posted_date |
| **Postgres 16 + arq** | SQLite plus legacy queue was stale; need queue plus dead letters | Postgres 16 + Redis 7 + arq |
| **No LinkedIn auto-apply** | LSTM detection, permanent bans | LinkedIn discovery only, external link |
| **LLM + verifier WARN@80** | Falsified templates; verifier catches hallucination | LLM generates → verifier WARN 70-79, hard 422 after 30 |
| **Cost ₹0/1k + ₹0-12/mo** | All discovery free, LLM only on skill | No LLM in batch, skill cache by jd_hash |

---

## Docker Compose

Postgres 16 is primary; `internapply/database.py` keeps SQLite only as CLI mirror/offline fallback.

```
postgres:16-alpine  — pgdata volume, healthcheck pg_isready
redis:7-alpine      — queue + breaker state
api                 — FastAPI (DATABASE_URL=postgresql+asyncpg://internapply:***@postgres:5432/internapply)
worker              — arq worker (same image, python -m backend.app.worker)
proxybroker         — free proxy rotation for JobSpy
ui                  — Next.js frontend
```

`DATABASE_URL` uses service name `postgres` not `localhost` — required for Docker networking.

---

## Known Issues / Tech Debt

1. **LinkedIn 999** — Hostile 999 response opens breaker 60s; wreq-js sidecar is optional fallback for JA3 fingerprint.
2. **Free overflow noise** — Tier3 EU/US feeds 90%+ filtered for Bangalore narrow; kept for overflow only.
3. **LLM token cost** — Skill only, cached by jd_hash; batch never calls LLM. ₹0-12/mo.
4. **Resume CGPA** — Needs manual update in profile/resume.json via `internapply resume edit`.
5. **All API keys checked by doctor** — System check shows green/red for each, plus working_boards KPI.

---

## How to Extend

### Add a new job source
1. Create `backend/app/discovery/newsource.py` with async `search() → list[dict]`
2. Add to `backend/app/worker.py` `discover_all` fanout
3. Add `*_ENABLED` flag in `config.py` and `.env.example`

### Add a new resume section
1. Update `profile/resume.json` with new fields
2. Update `internapply/resume/renderer.py` `render_resume()` to include it
3. The verifier will automatically check any new fields

### Modify the LLM prompt
- JD analyzer prompt: `internapply/resume/analyzer.py`
- Resume tailor prompt: `internapply/resume/tailor.py` + `.opencode/skills/resume-tailor/SKILL.md`
- Cover letter prompt: `internapply/resume/cover_letter.py`
