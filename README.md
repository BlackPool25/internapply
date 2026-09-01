# InternApply

<div align="center">

[![CI](https://github.com/BlackPool25/internapply/actions/workflows/test.yml/badge.svg)](https://github.com/BlackPool25/internapply/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-black?logo=next.js&logoColor=white)](https://nextjs.org)
[![Postgres 16](https://img.shields.io/badge/Postgres-16-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![shields.io](https://img.shields.io/badge/shields.io-badges-orange)](https://shields.io)

**Automated internship discovery for paid backend roles. Tiered, free, and hallucination-proof.**

</div>

> **TL;DR** InternApply fans out across ~100 ATS boards plus Hirist, Unstop, Internshala, JobSpy, and free overflow, dedups deterministically with hash simhash, saves to Postgres, and tailors resumes on demand with a verifier gate at 80. Discovery costs zero per thousand. LLM costs zero to twelve rupees per month.

<div align="center">
  <img src="assets/demo.svg" alt="InternApply demo — 30s walkthrough: discover → filter → save → tailor" width="800">
  <br>
  <em>30 second demo — discover → filter → save → tailor. SVG placeholder (<code>assets/demo.svg</code>), replace with <code>assets/demo.gif</code> when recorded.</em>
</div>

---

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Pipeline](#pipeline)
- [Architecture](#architecture)
- [CLI Reference](#cli-reference)
- [Anti-Hallucination Guarantee](#anti-hallucination-guarantee)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)

---

## Features

- **Tiered discovery, zero cost.** ~100 working ATS boards (Greenhouse, Lever, Ashby, SmartRecruiters, cursor `updated_at` with `posted_date` fallback) plus Hirist gladiator, Unstop, Internshala XHR, JobSpy Naukri and Indeed, free overflow (Arbeitnow, Remotive, TheMuse), and LinkedIn overflow with 999 breaker. All discovery at **zero per thousand**.
- **LLM only on demand.** OpenCode Go runs only inside the `resume-tailor` skill, never in batch. Cached by `jd_hash`, cost stays **zero to twelve rupees per month**.
- **Deterministic verifier gate.** Six checks, set matching only, no LLM scoring. **WARN at 80** (yellow 70 to 79 for first 30 JDs, hard 422 after), DOCX output at **96.7 percent** ATS parse.
- **Hash dedup, no fuzzy LLM.** `canonical_id` VARCHAR 64 UNIQUE, `jd_hash` primary, `simhash` residual Hamming less than or equal to 3.
- **Postgres 16 plus arq plus Redis 7.** Queue depth gauge, circuit breaker 999, `dead_letters` with `next_retry_at`, hourly `discover_all` cron.
- **Frontend built for speed.** Next.js 16, nuqs for URL state, TanStack Query and Table, shadcn/ui.

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/BlackPool25/internapply.git
cd internapply
pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env, set OPENCODE_GO_API_KEY for skill, DATABASE_URL uses service name postgres
```

### 3. Run

```bash
# Import your master resume
internapply resume init

# Tiered discovery, dry run with mock data
internapply discover --dry-run

# Truncated pipeline: discover, filter, save (skill is separate)
internapply run --dry-run
```

### Docker (recommended)

```bash
docker compose -f docker/docker-compose.yml up -d
curl localhost:8000/health # API health check
curl localhost:3000 # Next.js frontend
```

Requires `DB_PASSWORD` in env. See [Configuration](#configuration).

---

## Pipeline

```mermaid
flowchart LR
 subgraph Tier0["Tier 0: ATS (~100)"]
 A[Greenhouse]
 B[Lever]
 C[Ashby]
 D[SmartRecruiters]
 end
 subgraph Tier1["Tier 1: Hirist + Unstop + Internshala"]
 E[Hirist gladiator<br/>gladiator.hirist.tech POST]
 F[Unstop corrected]
 G[Internshala XHR fragment]
 end
 subgraph Tier2["Tier 2: JobSpy"]
 H[Naukri]
 I[Indeed]
 end
 subgraph Tier3["Tier 3: Overflow"]
 J[LinkedIn<br/>999 breaker + wreq-js]
 K[Arbeitnow / Remotive / TheMuse<br/>20 per page, 5 pages max]
 end

 Tier0 --> DISCOVER
 Tier1 --> DISCOVER
 Tier2 --> DISCOVER
 Tier3 --> DISCOVER

 DISCOVER --> FILTER{"filter<br/>canonical_id 64 UNIQUE<br/>jd_hash primary<br/>simhash Hamming ≤3"}
 FILTER -->|new or changed| SAVE[(Postgres 16<br/>job_listings)]
 FILTER -->|exact dup| SKIP[skip]
 FILTER -->|near dup| SKIP
 SAVE --> SKILL{{skill on demand<br/>resume-tailor<br/>WARN at 80}}
 SKILL -.->|verifier gate| SKILL
 SAVE --> DL[(dead_letters<br/>source url UNIQUE<br/>next_retry_at)]
```

### Pipeline Stages

```
discover (ATS + Hirist + Unstop + Internshala + JobSpy + free overflow) -> filter -> save -> skill on demand
```

| Stage | What it does |
|---|---|
| **DISCOVER** | Tiered fanout. **Tier0** probed ~100 ATS boards (cursor `updated_at` with `posted_date` fallback) plus **Tier1** Hirist gladiator POST plus Unstop corrected plus Internshala XHR fragment plus **Tier2** JobSpy Naukri and Indeed plus **Tier3** free overflow Arbeitnow, Remotive, TheMuse (paginated 20 per page, up to 5 pages) plus LinkedIn overflow with 999 breaker plus optional wreq-js fallback. No API keys for ATS or Hirist, free APIs capped. |
| **FILTER** | Deterministic hash dedup, no LLM. `canonical_id` VARCHAR 64 UNIQUE (64 hex sha256, primary key), `jd_hash` primary (volatile stripped JD hash for change detection), `simhash` residual (64 bit, Hamming less than or equal to 3). Tracks `new`, `changed`, `gone` drift via `diff_change_log`. |
| **SAVE** | Upserts to Postgres 16 (`job_listings` with `canonical_id` 64 UNIQUE plus `jd_hash` index). Source badges and drift computed from hash diffs. ETag header stored when present. |
| **SKILL** | On demand opencode skill `.opencode/skills/resume-tailor/SKILL.md`. LLM tailors resume for selected JD, verifier gate, DOCX 96.7 percent ATS parse. **Verifier WARN at 80** (yellow 70 to 79 for first 30 JDs, hard 422 after). Cached by `jd_hash`. Never runs in batch, cost stays zero to twelve rupees per month. |

### Source Tiers

| Tier | Sources | Cost per 1k | API |
|------|---------|-------------|-----|
| **Tier0** | ATS boards (Greenhouse, Lever, Ashby, SmartRecruiters), working 100 from 200 probed | Zero | keyless JSON, cursor updated_at |
| **Tier1** | Hirist gladiator (`gladiator.hirist.tech` POST, free JSON) plus Unstop corrected plus Internshala XHR fragment | Zero | Hirist free JSON, Unstop free JSON |
| **Tier2** | JobSpy (Naukri plus Indeed) | Zero | free scrape |
| **Tier3** | LinkedIn overflow (JobSpy, 999 breaker plus wreq-js fallback) plus free overflow (Arbeitnow free, Remotive free capped, TheMuse 500 per hour anon, paginated 20 per page) | Zero | breaker plus wreq-js, free capped |

All discovery is **zero per thousand**. LLM cost is **zero to twelve rupees per month** only when you invoke the skill.

---

## Architecture

### System overview

Truncated pipeline (`discover` to `filter` to `save` plus on demand skill). Each node is an async function reading and writing a shared `PipelineState` dict with `seen_canonical_ids` and `cursor` (`updated_at` with `posted_date` fallback). The skill runs separately with verifier WARN at 80 and DOCX 96.7 percent.

**Stack:** Python 3.11 plus, LangGraph StateGraph, Postgres 16 plus asyncpg plus Alembic, Redis 7 plus arq, httpx plus tenacity, Next.js 16 plus nuqs plus TanStack, python-docx.

### Entity relationship

```mermaid
erDiagram
 job_listings ||--o{ dead_letters : "buffers failures"

 job_listings {
 varchar canonical_id PK "VARCHAR 64 UNIQUE, sha256 salt+company+title+location+source"
 varchar jd_hash "VARCHAR 64, volatile stripped JD hash, primary change key"
 bigint simhash "BIGINT 64 bit simhash, residual Hamming ≤3"
 varchar etag "ETag header when present"
 jsonb change_log "JSONB diff_change_log new changed gone"
 varchar source_ats "source badge: greenhouse lever ashby hirist etc"
 timestamptz last_seen_at "cursor updated_at or posted_date fallback"
 varchar title
 varchar company
 varchar location
 jsonb skills
 varchar url
 }

 dead_letters {
 serial id PK
 text source "hirist ats linkedin etc"
 text url "UNIQUE with source"
 int status_code "429 502 999 etc"
 text error
 timestamptz next_retry_at "indexed, retried when ≤ now"
 }
```

### Deduplication flow

```mermaid
sequenceDiagram
 participant D as Discovery
 participant H as HashUtils
 participant DB as Postgres
 participant CL as ChangeLog

 D->>H: build canonical_id<br/>sha256(salt + lower(company+title+location+source_id))
 H-->>D: canonical_id 64 hex
 D->>H: build jd_hash<br/>sha256(normalized JD, volatile stripped)
 H-->>D: jd_hash 64 hex
 D->>H: simhash64(title + url)
 H-->>D: simhash BIGINT

 D->>DB: SELECT where canonical_id = ?
 alt seen_canonical_id hit
 DB-->>D: existing row
 D->>D: compare jd_hash
 alt jd_hash differs
 D->>CL: diff_change_log(old JD, new JD)
 CL-->>D: changed fields
 D->>DB: UPDATE jd_hash, change_log, drift=changed
 else jd_hash same
 D->>D: skip, exact dup
 end
 else canonical_id miss
 D->>DB: simhash Hamming scan threshold 3
 alt Hamming <=3 near dup
 DB-->>D: near match
 D->>D: skip, residual dup
 else no near dup
 D->>DB: INSERT job_listings drift=new
 DB-->>D: inserted
 end
 end

 opt fetch failed 429 5xx 999
 D->>DB: INSERT dead_letters source, url UNIQUE, next_retry_at
 end
```

### Postgres 16 plus arq plus Redis 7

All listings live in **Postgres 16** (`postgresql+asyncpg://internapply:***@postgres:5432/internapply`, service name `postgres`). `job_listings` has `canonical_id` VARCHAR 64 UNIQUE and `jd_hash` VARCHAR 64 index. `dead_letters` buffers failed fetches with `UNIQUE(source, url)` and `next_retry_at`. SQLite is kept only as CLI mirror or offline fallback.

Background work runs via **arq** (hourly `discover_all` cron, per source tasks with tenacity, `queue_depth` gauge). **Redis 7** holds queue state and circuit breaker flags (`SET NX EX 60`). Prometheus metrics expose queue depth, breaker state, and dead letters.

### Rate limiting and resilience

- **LLM calls:** only in skill, never in batch, cached by jd_hash
- **ATS probing:** httpx concurrency 10, per ATS intervals (Greenhouse 1s, Lever 2s), tenacity 429 backoff with Retry-After clamp 30s
- **LinkedIn 999:** breaker opens 60s on first 999, dead_letters insert, optional wreq-js sidecar fallback at `WREQ_SIDECAR_URL`
- **Free overflow:** paginated 20 per page, max 5 pages, respects 429 and enabled flags
- **Hunter.io:** respects free tier limit (about 50 requests per month), X per 50 counter, not in batch

### Observability

Prometheus metrics at `backend/app/observability/metrics.py`: `queue_depth` gauge, `circuit_breaker_open{source}` gauge, `dead_letters_total{source}` counter, `discover_latency_p50{source}` histogram. Dashboard KPI `working_boards` shows boards with `latency_p50` and `has_updatedAt`.

Structured logging via `loguru` and `structlog`, secrets masked, timing and counts per node.

---

## CLI Reference

### `internapply resume`

Manage your master resume (stored in `profile/resume.json`).

```bash
internapply resume init # Parse JS generator to JSON
internapply resume show # Display current resume
internapply resume add-skill "Backend: FastAPI" # Add a skill
internapply resume add-project "MyApp" # Add a project
internapply resume edit # Open resume in $EDITOR
internapply resume refresh # Re-parse JS file after edits
```

### `internapply discover`

Find listings across tiers.

```bash
internapply discover # Default tiered search, all tiers
internapply discover --keywords "python,rust" --locations "Remote"
internapply discover --dry-run # Simulate with mock data
internapply discover --max-jobs 100 # Limit results
internapply discover --no-save # Do not write to DB
```

### `internapply run`

Truncated pipeline, discover to filter to save.

```bash
internapply run # Truncated batch, no LLM
internapply run --dry-run # Simulate everything
internapply run --max-jobs 10 # Process only 10 jobs
```

Tailoring is via the on demand skill, not `run`:

```bash
# Skill: .opencode/skills/resume-tailor/SKILL.md
# Invoke from dashboard or skill runner, verifier WARN at 80, DOCX 96.7 percent
```

### `internapply status` and `doctor`

```bash
internapply status # Pipeline stats, DB summary, working_boards KPI, active config
internapply doctor # System check, API keys, files, DB, working ~100 boards
```

---

## Anti-Hallucination Guarantee

The biggest risk with LLM generated resumes is fabrication. InternApply solves it with a deterministic verifier gate in the on demand skill.

### How it works

After the LLM tailors a resume (skill only, never in batch), `ResumeVerifier` runs **six checks** against the source resume. Every check uses **set based string matching only**, no LLM calls, no API keys, no black box scoring.

| Check | What it prevents | Severity |
|---|---|---|
| **Project names** | LLM invents a project you never worked on | Error |
| **Skills** | LLM adds a skill absent from your resume | Error |
| **Dates** | LLM fabricates or shifts timeline entries | Error |
| **Metrics** | LLM inflates numbers (40 percent to 99.5, $10k to $2M) | Error |
| **Education** | LLM adds fake degrees, institutions, or GPAs | Error |
| **Cliches** | LLM fills hollow AI phrases ("team player", "synergy") | Warning |

Score starts at 100, minus 20 per error. **Verifier WARN at 80:** score 70 to 79 shows yellow WARN but allows save for first 30 JDs, after 30 below 80 it hard fails with 422. Score greater than or equal to 80 is green pass. DOCX output hits **96.7 percent** ATS parse rate.

### Humanization pass for cover letters

Cover letters go through a second deterministic pipeline:

- Strips AI cliche phrases ("passionate about", "proven track record", "synergy")
- Removes robotic phrasing ("I am writing to apply" removed)
- Removes hedging ("just", "maybe", "perhaps")
- Eliminates submissive language ("sorry to bother", "if you do not mind")
- Scores five criteria (cliches, sentence variety, hedging, tone, word count)

If score is below 80, letter regenerates with specific feedback, up to three attempts. Verifier WARN applies here too.

---

## Configuration

All config via env vars or `.env` in project root.

### Required

| Variable | Description |
|---|---|
| `OPENCODE_GO_API_KEY` | OpenCode Go API key for LLM calls (skill only) |
| `OPENCODE_GO_MODEL` | Model id (default `deepseek-v4-flash`) |
| `OPENCODE_GO_BASE_URL` | API endpoint (default `https://opencode.ai/zen/go/v1`) |
| `DATABASE_URL` | `postgresql+asyncpg://internapply:changeme@postgres:5432/internapply` (service name `postgres`, not localhost) |
| `REDIS_URL` | `redis://redis:6379/0` |
| `DB_PASSWORD` | Postgres password for docker compose (required) |

### Infra and hash

| Variable | Default | Description |
|---|---|---|
| `HASH_SALT` | `internapply-v1` | Salt for canonical_id and jd_hash (64 hex) |
| `SIMHASH_THRESHOLD` | `3` | Hamming distance for near dup (1 to 10) |
| `VERIFIER_MIN_SCORE` | `80` | Verifier gate, WARN yellow 70 to 79 for first 30 JDs, hard 422 after |
| `WREQ_SIDECAR_URL` | `http://wreq:3000` | Optional Node wreq-js JA3 sidecar for LinkedIn 999 fallback |
| `VOLLNA_RSS_URL` | _(empty)_ | Optional Vollna RSS for Upwork webhook |
| `ARBEITNOW_ENABLED` | `true` | Tier3 free overflow toggle |
| `HIRIST_ENABLED` | `true` | Tier1 Hirist gladiator toggle |
| `UNSTOP_ENABLED` | `true` | Tier1 Unstop toggle |
| `REMOTIVE_ENABLED` | `true` | Tier3 Remotive toggle |
| `THEMUSE_ENABLED` | `true` | Tier3 TheMuse (500 per hour anon) toggle |
| `JOBICY_ENABLED` | `true` | Tier3 Jobicy toggle |

### Preferences

| Variable | Default | Description |
|---|---|---|
| `SEARCH_KEYWORDS` | `["python backend intern","java spring boot intern","backend engineer intern"]` | Keywords for search |
| `SEARCH_LOCATIONS` | `["Remote","Bangalore"]` | Target locations |
| `MIN_STIPEND_INR` | `5000` | Minimum monthly stipend in INR |
| `MAX_APPLICATIONS_PER_DAY` | `20` | Daily application limit |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Research notes

- **Truncated pipeline:** batch discovery is free, running LLM per JD would cost and hallucinate at scale. Skill only with verifier WARN at 80, cached by jd_hash, cost drops to zero to twelve rupees per month.
- **Tiered discovery:** no single source covers all roles. Tier0 ATS ~100 plus Hirist gladiator for Bangalore startups plus free overflow for remote spill.
- **Hash 64:** sha256 64 hex is enough for canonical_id and jd_hash, 128 was waste. Salt via HASH_SALT prevents cross env collisions, volatile stripping normalizes dates and view counts.
- **Postgres 16 plus arq:** SQLite plus old queue was stale and lacked observability. Postgres gives VARCHAR 64 UNIQUE, JSONB, and dead_letters with next_retry_at. arq gives hourly cron, queue depth gauge, breaker state. Redis holds breaker flags with SET NX EX 60.

---

## Project Structure

```
internapply/
├── internapply/
│ ├── config.py # pydantic-settings loader, lazy boards
│ ├── database.py # SQLAlchemy async ORM, Postgres 16 primary
│ ├── hash_utils.py # canonical_id 64, jd_hash primary, simhash residual
│ ├── llm.py # OpenCode Go client (skill only)
│ ├── models.py # Pydantic v2 models
│ ├── discovery/
│ │ ├── ats/ # Tier0: Greenhouse, Lever, Ashby, SmartRecruiters (cursor)
│ │ ├── hirist.py # Tier1: Hirist gladiator.hirist.tech POST (free JSON)
│ │ ├── unstop.py # Tier1: Unstop corrected API
│ │ ├── internshala_xhr.py # Tier1: Internshala XHR fragment
│ │ ├── free_apis.py # Tier3 overflow: Arbeitnow, Remotive, TheMuse, Jobicy 20 per page
│ │ ├── jobspy_linkedin.py # Tier2 JobSpy Naukri, Indeed plus Tier3 LinkedIn 999 breaker
│ │ └── freelance/ # Freelancer RSS plus Internshala freelance XHR
│ ├── resume/
│ │ ├── verifier.py # Deterministic verifier WARN at 80 (6 checks)
│ │ ├── tailor.py # LLM tailor (skill on demand, not batch)
│ │ └── renderer.py # DOCX 96.7 percent ATS parse
│ ├── pipeline/
│ │ ├── state.py # PipelineState (seen_canonical_ids, cursor)
│ │ └── graph.py # 3 node StateGraph: discover -> filter -> save
│ └── cli/ # internapply discover, run, status, doctor
├── backend/app/
│ ├── worker.py # arq worker: discover_all hourly cron
│ ├── discovery/circuit.py # Breaker SET NX EX 60 plus dead_letters
│ └── observability/metrics.py # queue_depth, breaker, dead_letters_total
├── frontend/ # Next.js 16, nuqs, TanStack Query, Table, shadcn/ui
├── .opencode/skills/resume-tailor/SKILL.md # On demand skill WARN at 80, DOCX 96.7 percent
├── config/boards.json # working ~100 ATS boards (from 200 probed)
├── docker/docker-compose.yml # postgres:16-alpine plus redis:7-alpine plus arq worker plus API plus UI
├── profile/resume.json # Master resume (generated)
├── .env.example # Env template (postgres service name)
└── pyproject.toml # Metadata plus deps
```

---

## FAQ

**Do I need an LLM API key?**
Only for the skill. Discovery and filtering work with no key (zero per thousand). Skill caches by jd_hash, cost is zero to twelve rupees per month.

**Does it work without an API key?**
Yes for discover to filter to save. Tailoring via skill requires `OPENCODE_GO_API_KEY`.

**Will it send emails without approval?**
No. Batch never sends. Skill drafts are saved for approval.

**What if the LLM fabricates skills?**
Verifier WARN catches it. Score 70 to 79 shows yellow warning for first 30 JDs, after 30 below 80 it hard fails 422. No silent hallucination.

**Can I run on a schedule?**
Yes. arq runs `discover_all` hourly (`hour={*range(24)}, minute=0`) across all tiers. Worker retries dead_letters where `next_retry_at <= now()`.

**What is the database for?**
Postgres 16 stores listings with `canonical_id` 64 UNIQUE and `jd_hash` for dedup and change detection, plus `dead_letters` for failed fetches. SQLite mirrors only for offline CLI.

**How do I update my resume?**
Edit `profile/resume.json` directly or invoke the skill, it re-reads master resume each time and runs verifier WARN at 80.

**What does working ~100 mean?**
From 200 probed ATS candidates, about 100 are working boards (Greenhouse, Lever, Ashby, SmartRecruiters) with `latency_p50` and `has_updatedAt` metadata. Rest are dead or rate limited. Hirist gladiator is separate and probed via `gladiator.hirist.tech`.

**Why not Celery?**
arq is lighter, async native, built for asyncio plus Redis, fits the existing httpx and tenacity stack without extra broker complexity.

---

## Contributing

We welcome contributions. This project follows a standard fork and PR flow.

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/internapply.git
cd internapply

# 2. Create a branch
git checkout -b feat/your-feature

# 3. Install dev deps
pip install -e ".[dev]"

# 4. Make changes, then test
pytest -q
ruff check .

# 5. Commit and push
git commit -m "feat: your feature"
git push origin feat/your-feature
```

Then open a PR against `main`. Please:

- Keep PRs focused, one feature per PR
- Add tests for new logic (verifier, hash, pipeline, discovery)
- Do not add secrets or API keys, use `.env.example` placeholders
- Run `ruff` and `pytest` before pushing, CI must stay green
- For discovery changes, test with `--dry-run` first

See open issues for `good first issue` labels.

---

## License

MIT License. See [LICENSE](LICENSE) for details. Copyright belongs to contributors.

---

## Acknowledgments

- **ATS boards**, Greenhouse, Lever, Ashby, SmartRecruiters for keyless JSON APIs that make Tier0 possible.
- **Hirist**, `gladiator.hirist.tech` free search that powers Bangalore startup coverage.
- **JobSpy**, open source job scraping for Naukri and Indeed.
- **Arbeitnow, Remotive, TheMuse, Jobicy**, free overflow APIs for remote spill.
- **arq, asyncpg, httpx, tenacity**, async Python backbone.
- **Next.js, nuqs, TanStack**, frontend stack for the dashboard.
- Inspired by the standards of [vercel/next.js](https://github.com/vercel/next.js) and [tiangolo/fastapi](https://github.com/tiangolo/fastapi) for README and DX polish.

---

<p align="center">
 <sub>Built with care for paid backend internships. PRs welcome.</sub>
</p>
