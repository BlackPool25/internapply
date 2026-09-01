# InternApply

**Automated internship application system for paid backend internships.**

InternApply discovers internship listings across tiered sources, filters with hash dedup, saves to Postgres, and tailors resumes on demand via an opencode skill with a verifier gate.

- Discovers from **~100 working ATS boards** (Greenhouse/Lever/Ashby/SmartRecruiters, cursor updated_at|posted_date) + **Hirist gladiator** + **Unstop** + **Internshala XHR** + **JobSpy Naukri/Indeed** + **free overflow** (Arbeitnow/Remotive/TheMuse)
- Uses an **LLM** (OpenCode Go) only in the **on-demand skill** (never in batch)
- Deterministic **verifier gate** ≥80 WARN (hard 422 after 30 JDs, yellow 70-79) + **DOCX 96.7%** ATS parse
- **Hash dedup**: canonical_id 64 UNIQUE, jd_hash primary, simhash residual (Hamming ≤3)
- **Postgres 16 + arq + Redis 7** — queue depth, circuit breaker (999), dead_letters
- **Cost**: discovery **₹0/1k** + LLM **₹0-12/mo** (skill only, cached by jd_hash)

```mermaid
flowchart LR
    DISCOVER --> FILTER --> SAVE --> SKILL
    SKILL -.->|verifier WARN@80| SKILL
```

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/your-username/internapply.git
cd internapply
pip install -e .

# 2. Set up your API keys
cp .env.example .env
# Edit .env with your OPENCODE_GO_API_KEY, DATABASE_URL uses service name postgres

# 3. Import your resume
internapply resume init

# 4. Find internships (tiered: ATS+Hirist+Unstop+Internshala+JobSpy+free overflow)
internapply discover --dry-run

# 5. Run the truncated pipeline
internapply run --dry-run   # discover → filter → save (skill is separate)
```

Or with Docker:

```bash
docker compose -f docker/docker-compose.yml up -d
curl localhost:8000/health
```

---

## Pipeline Stages

```
discover (ATS+Hirist+Unstop+Internshala+JobSpy+free overflow) → filter → save → skill on-demand
```

| Stage | What it does |
|---|---|
| **DISCOVER** | Tiered fanout: **Tier0** probed ~100 ATS boards (cursor updated_at\|posted_date fallback) + **Tier1** Hirist gladiator POST + Unstop corrected + Internshala XHR fragment + **Tier2** JobSpy Naukri/Indeed + **Tier3** free overflow Arbeitnow/Remotive/TheMuse (paginated 20/page, up to 5 pages) + LinkedIn overflow with 999 breaker + optional wreq-js fallback. No API keys for ATS/Hirist, free APIs capped. |
| **FILTER** | Deterministic hash dedup (no LLM): `canonical_id` VARCHAR(64) UNIQUE (64 hex sha256, primary key), `jd_hash` primary (volatile-stripped JD hash for change detection), `simhash` residual (64-bit, Hamming ≤3). Tracks `new/changed/gone` drift via `diff_change_log`. |
| **SAVE** | Upserts to Postgres 16 (`job_listings` with `canonical_id 64 UNIQUE` + `jd_hash` index). Source badges + drift computed from hash diffs. ETag header stored when present. |
| **SKILL** | On-demand opencode skill `.opencode/skills/resume-tailor/SKILL.md`: LLM tailors resume for the selected JD → verifier gate → DOCX 96.7% ATS parse. **Verifier ≥80 WARN** (yellow 70-79 for first 30 JDs, hard 422 after). Cached by `jd_hash`. Never runs in batch — cost stays ₹0-12/mo. |

### Source Tiers

| Tier | Sources | Cost/1k | API/Push |
|------|---------|---------|----------|
| **Tier0** | ATS boards (Greenhouse, Lever, Ashby, SmartRecruiters) — working 100 from 200 probed | ₹0 | keyless JSON, cursor updated_at |
| **Tier1** | Hirist gladiator (`gladiator.hirist.tech` POST, free JSON) + Unstop corrected + Internshala XHR fragment | ₹0 | Hirist free JSON, Unstop free JSON |
| **Tier2** | JobSpy (Naukri + Indeed) | ₹0 | free scrape |
| **Tier3** | LinkedIn overflow (JobSpy, 999 breaker + wreq-js fallback) + free overflow (Arbeitnow free, Remotive free capped, TheMuse 500/hr anon, paginated 20/page) | ₹0 | breaker + wreq-js, free capped |

All discovery is **₹0/1k**. LLM cost is **₹0-12/mo** only when you invoke the skill.

---

## CLI Commands

### `internapply resume`

Manage your master resume (stored in `profile/resume.json`).

```
internapply resume init                          Parse JS resume generator → JSON
internapply resume show                          Display current resume
internapply resume add-skill "Backend: FastAPI"  Add a skill
internapply resume add-project "MyApp"           Add a project
internapply resume edit                          Open resume in $EDITOR
internapply resume refresh                       Re-parse JS file after edits
```

### `internapply discover`

Find internship listings (tiered).

```
internapply discover                                      Default tiered search (all tiers)
internapply discover --keywords "python,rust" --locations "Remote"
internapply discover --dry-run                            Simulate (uses mock data)
internapply discover --max-jobs 100                       Limit results
internapply discover --no-save                            Don't write to DB
```

### `internapply run`

Execute the truncated pipeline (discover → filter → save).

```
internapply run                                           Truncated batch (no LLM)
internapply run --dry-run                                 Simulate everything
internapply run --max-jobs 10                             Process only 10 jobs
```

Tailoring is via the on-demand skill, not `run`:

```
# Skill: .opencode/skills/resume-tailor/SKILL.md
# Invoke from dashboard or: use the skill to tailor for a JD (verifier WARN@80, DOCX 96.7%)
```

### `internapply status`

Show pipeline statistics, database summary, working_boards KPI, and active configuration.

---

## Anti-Hallucination Guarantee

The biggest risk with LLM-generated resumes is fabrication. InternApply solves
this with a deterministic verifier gate in the on-demand skill.

### How it works

After the LLM tailors a resume (skill only, never in batch), the `ResumeVerifier` runs **6 checks** against
the source resume. Every check uses **set-based string matching only**:
no LLM calls, no API keys, no black-box scoring.

| Check | What it prevents | Severity |
|---|---|---|
| **Project names** | LLM invents a project you never worked on | Error |
| **Skills** | LLM adds a skill that isn't in your resume | Error |
| **Dates** | LLM fabricates or shifts timeline entries | Error |
| **Metrics** | LLM inflates numbers (40% → 99.5%, $10k → $2M) | Error |
| **Education** | LLM adds fake degrees, institutions, or GPAs | Error |
| **Cliches** | LLM fills in hollow AI phrases ("team player", "synergy") | Warning |

The score starts at 100 and drops by 20 points per error. **Verifier ≥80 WARN**: score 70-79 shows yellow WARN but allows save for the first 30 JDs; after 30 JDs below 80, the gate hard-fails with 422. Score ≥80 is green pass. DOCX output hits **96.7%** ATS parse rate.

### Humanization pass for cover letters

Cover letters go through a second deterministic pipeline that:

- Strips AI cliche phrases ("passionate about", "proven track record", "synergy")
- Replaces robotic phrasing ("I am writing to apply" → removed)
- Removes hedging language ("just", "maybe", "perhaps")
- Eliminates submissive language ("sorry to bother", "if you don't mind")
- Scores 5 criteria (cliches, sentence variety, hedging, tone, word count)

If the score is below 80, the letter is regenerated with specific feedback (up to 3 attempts). Verifier WARN applies here too.

---

## Architecture

### Truncated pipeline (discover → filter → save → skill)

The pipeline is a `StateGraph` with 3 nodes (discover → filter → save) plus an on-demand skill. Each node is an async function that reads and writes to a shared `PipelineState` dict with `seen_canonical_ids` and `cursor` (updated_at|posted_date fallback). The skill runs separately with verifier WARN@80 and DOCX 96.7%.

### Postgres 16 + arq + Redis 7

All job listings are stored in **Postgres 16** (`postgresql+asyncpg://internapply:***@postgres:5432/internapply`, service name `postgres`). The `job_listings` table has `canonical_id VARCHAR(64) UNIQUE` and `jd_hash VARCHAR(64)` index. `dead_letters` buffers failed fetches with `UNIQUE(source, url)` and `next_retry_at`. SQLite is kept only as CLI mirror/offline fallback.

Background work runs via **arq** (hourly `discover_all` cron, per-source tasks with tenacity, `queue_depth` gauge). **Redis 7** holds queue state and circuit breaker flags (`SET NX EX 60`). Prometheus metrics expose queue depth, breaker state, and dead letters.

### Secure token storage

Gmail OAuth tokens are encrypted at rest using `cryptography.fernet`. The
encryption key is derived from the machine ID and an optional passphrase.

### Rate limiting & resilience

- **LLM calls**: Only in skill, never in batch; cached by jd_hash
- **ATS probing**: httpx concurrency 10, per-ATS intervals (Greenhouse 1s, Lever 2s), tenacity 429 backoff with Retry-After clamp 30s
- **LinkedIn 999**: breaker opens 60s on first 999, dead_letters insert, optional wreq-js sidecar fallback
- **Free overflow**: paginated 20/page, max 5 pages, respects 429 and enabled flags
- **Hunter.io**: Respects the free tier limit (~50 requests/month), X/50 counter, not in batch

### Structured logging

All pipeline nodes log timing, item counts, and error details via `loguru`/`structlog`.
Configuration and API keys are logged once at startup (with secrets masked).

---

## Configuration

All configuration is via environment variables or a `.env` file in the project
root.

### Required

| Variable | Description |
|---|---|
| `OPENCODE_GO_API_KEY` | OpenCode Go API key for LLM calls (skill only) |
| `OPENCODE_GO_MODEL` | Model identifier (default: `deepseek-v4-flash`) |
| `OPENCODE_GO_BASE_URL` | API endpoint (default: `https://opencode.ai/zen/go/v1`) |
| `DATABASE_URL` | `postgresql+asyncpg://internapply:changeme@postgres:5432/internapply` (service name `postgres`, not localhost) |
| `REDIS_URL` | `redis://redis:6379/0` |

### Infra & Hash

| Variable | Default | Description |
|---|---|---|
| `HASH_SALT` | `internapply-v1` | Salt for canonical_id / jd_hash (64 hex) |
| `SIMHASH_THRESHOLD` | `3` | Hamming distance for near-dup (1-10) |
| `VERIFIER_MIN_SCORE` | `80` | Verifier gate: WARN yellow 70-79 for first 30 JDs, hard 422 after |
| `WREQ_SIDECAR_URL` | `http://wreq:3000` | Optional Node wreq-js JA3 sidecar for LinkedIn 999 fallback |
| `VOLLNA_RSS_URL` | (empty) | Optional Vollna RSS for Upwork webhook |
| `ARBEITNOW_ENABLED` | `true` | Tier3 free overflow toggle |
| `HIRIST_ENABLED` | `true` | Tier1 Hirist gladiator toggle |
| `UNSTOP_ENABLED` | `true` | Tier1 Unstop toggle |
| `REMOTIVE_ENABLED` | `true` | Tier3 Remotive toggle |
| `THEMUSE_ENABLED` | `true` | Tier3 TheMuse (500/hr anon) toggle |

### Preferences

| Variable | Default | Description |
|---|---|---|
| `SEARCH_KEYWORDS` | `["python backend intern","java spring boot intern","backend engineer intern"]` | Keywords for internship search |
| `SEARCH_LOCATIONS` | `["Remote","Bangalore"]` | Target locations |
| `MIN_STIPEND_INR` | `5000` | Minimum monthly stipend in INR |
| `MAX_APPLICATIONS_PER_DAY` | `20` | Daily application limit |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

---

## Research Findings

### Why truncated pipeline (no LLM in batch)

Batch discovery is free (₹0/1k). Running LLM for every JD in batch would cost and hallucinate at scale. The skill runs only on demand with verifier WARN@80, cached by jd_hash — cost drops to ₹0-12/mo.

### Why tiered discovery

No single source covers all roles. Tier0 ATS ~100 working boards covers Greenhouse/Lever/Ashby/SmartRecruiters with cursor updated_at. Tier1 Hirist gladiator adds Bangalore startup coverage (free JSON). Tier3 free overflow (Arbeitnow/Remotive/TheMuse) catches remote spillover, even if 90%+ is filtered.

### Why hash 64

sha256 64 hex is sufficient for canonical_id and jd_hash. 128 was waste. Salt via HASH_SALT prevents cross-env collisions. Volatile stripping normalizes dates and view counts before hashing.

### Why Postgres 16 + arq

SQLite plus the old queue was stale and lacked observability. Postgres 16 gives `VARCHAR(64) UNIQUE`, JSONB, and `dead_letters` with `next_retry_at`. arq provides hourly cron, queue depth gauge, and breaker state. Redis 7 holds breaker flags with `SET NX EX 60`.

---

## Project Structure

```
internapply/
├── internapply/
│   ├── config.py                  # pydantic-settings config loader (lazy boards)
│   ├── database.py                # SQLAlchemy async ORM — Postgres 16 primary
│   ├── hash_utils.py              # canonical_id 64, jd_hash primary, simhash residual
│   ├── llm.py                     # OpenCode Go LLM client (skill only)
│   ├── models.py                  # Pydantic v2 data models
│   │
│   ├── discovery/
│   │   ├── ats/                   # Tier0: Greenhouse/Lever/Ashby/SmartRecruiters (cursor)
│   │   ├── hirist.py              # Tier1: Hirist gladiator.hirist.tech POST (free JSON)
│   │   ├── unstop.py              # Tier1: Unstop corrected API
│   │   ├── internshala_xhr.py     # Tier1: Internshala XHR fragment
│   │   ├── free_apis.py           # Tier3 overflow: Arbeitnow/Remotive/TheMuse/Jobicy 20/page
│   │   ├── jobspy_linkedin.py     # Tier2 JobSpy Naukri/Indeed + Tier3 LinkedIn 999 breaker
│   │   └── freelance/             # Freelancer RSS + Internshala freelance XHR
│   │
│   ├── resume/
│   │   ├── verifier.py            # Deterministic verifier WARN@80 (6 checks)
│   │   ├── tailor.py              # LLM tailor (skill on-demand, not batch)
│   │   └── renderer.py            # DOCX 96.7% ATS parse
│   │
│   ├── pipeline/
│   │   ├── state.py               # PipelineState (seen_canonical_ids, cursor)
│   │   └── graph.py               # 3-node StateGraph: discover → filter → save
│   │
│   └── cli/                       # internapply discover / run / status / doctor
│
├── backend/app/
│   ├── worker.py                  # arq worker: discover_all hourly cron
│   ├── discovery/circuit.py       # Breaker SET NX EX 60 + dead_letters
│   └── observability/metrics.py   # queue_depth, breaker, dead_letters_total
│
├── .opencode/skills/resume-tailor/SKILL.md  # On-demand skill WARN@80, DOCX 96.7%
├── config/boards.json             # working ~100 ATS boards (from 200 probed)
├── docker/docker-compose.yml      # postgres:16-alpine + redis:7-alpine + arq worker
├── profile/resume.json            # Your master resume (generated)
├── .env.example                   # Environment variable template (postgres service name)
└── pyproject.toml                 # Project metadata + dependencies
```

---

## FAQ

**Do I need an LLM API key?**
Only for the skill. Discovery and filtering work with no key (₹0/1k). The skill caches by jd_hash, so cost is ₹0-12/mo.

**Does this work without an API key?**
Yes for discovery → filter → save. Tailoring via skill requires `OPENCODE_GO_API_KEY`.

**Will InternApply send emails without me approving?**
No. Batch never sends. Skill drafts are saved for approval.

**What happens if the LLM fabricates skills?**
Verifier WARN catches it. Score 70-79 shows yellow warning for first 30 JDs; after 30 below 80 it hard-fails 422. No silent hallucination.

**Can I run this on a schedule?**
Yes. arq runs `discover_all` hourly (`hour={*range(24)}, minute=0`) across all tiers. The worker retries dead_letters where `next_retry_at <= now()`.

**What's the database for?**
Postgres 16 stores job listings with `canonical_id 64 UNIQUE` and `jd_hash` for dedup/change detection, plus `dead_letters` for failed fetches. SQLite mirrors only for offline CLI.

**How do I update my resume after initial setup?**
Edit `profile/resume.json` directly or invoke the skill — it re-reads the master resume each time and runs verifier WARN@80.

**What does `working ~100` mean?**
From 200 probed ATS candidates, ~100 are working boards (Greenhouse/Lever/Ashby/SmartRecruiters) with `latency_p50` and `has_updatedAt` metadata. The rest are dead or rate-limited. Hirist gladiator is separate and always probed via `gladiator.hirist.tech`.

