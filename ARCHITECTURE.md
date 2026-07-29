# InternApply — System Architecture

## Overview

InternApply is an automated internship application system. It discovers paid backend internships (Python/Java, remote/Bangalore) from Internshala, analyzes job descriptions, tailors your resume per company using LLM, generates cover letters, finds hiring manager emails via Hunter.io, sends cold emails with tailored resume attached, and auto-applies on Internshala via Playwright.

**Tech Stack**: Python 3.12, LangGraph, OpenCode Go (deepseek-v4-flash), SQLite, Playwright, Gmail API, Hunter.io, python-docx

---

## Project Structure

```
~/projects/internapply/
├── internapply/
│   ├── __init__.py
│   ├── config.py              # Pydantic-settings config from .env
│   ├── database.py            # Async SQLAlchemy + SQLite + migrations
│   ├── models.py              # Pydantic v2 data models
│   ├── llm.py                 # OpenCode Go API wrapper (OpenAI-compatible)
│   │
│   ├── discovery/             # Job discovery modules
│   │   ├── internshala.py     # HTTP scraper + detail page enrichment via JSON-LD
│   │   └── naukri.py          # Apify-only backend (dead actor — not used)
│   │
│   ├── resume/                # Resume engine
│   │   ├── parser.py          # Parses JS generator → structured JSON
│   │   ├── analyzer.py        # JD skill extraction (LLM + deterministic fallback)
│   │   ├── tailor.py          # LLM resume tailoring + Markdown renderer
│   │   ├── verifier.py        # Deterministic hallucination gate (6 checks)
│   │   ├── scorer.py          # ATS keyword scorer (0-100, deterministic)
│   │   ├── cover_letter.py    # LLM cover letter + humanization
│   │   └── renderer.py        # Professional DOCX resume generator
│   │
│   ├── outreach/              # Email outreach
│   │   ├── email_finder.py    # Hunter.io API + domain extraction + caching
│   │   └── sender.py          # Gmail API + encrypted tokens + attachments
│   │
│   ├── apply/                 # Auto-apply
│   │   ├── browser.py         # Playwright CDP browser manager
│   │   └── internshala.py     # Internshala form submission
│   │
│   ├── pipeline/              # LangGraph orchestration
│   │   ├── state.py           # PipelineState TypedDict
│   │   ├── graph.py           # StateGraph definition (7 nodes)
│   │   └── nodes.py           # Pipeline node functions (real implementations)
│   │
│   └── cli/                   # CLI interface
│       ├── main.py            # Typer app entry point
│       ├── resume.py          # Resume management commands
│       ├── discover.py        # Discovery command
│       ├── tailor.py          # Resume tailoring command
│       └── email.py           # Email management + Gmail setup
│       └── doctor.py          # System check command
│
├── tests/                     # 63 tests across 7 test files
├── .github/workflows/         # CI/CD + daily scheduled runs
├── profile/
│   ├── resume.json            # Master resume (canonical source)
│   └── github_data.json       # GitHub profile data
├── data/
│   └── internapply.db         # SQLite database
├── applications/              # Generated applications per company
├── .env                       # API keys and configuration
├── pyproject.toml             # Dependencies
├── README.md                  # User documentation
├── SETUP.md                   # Setup guide
└── ARCHITECTURE.md            # This file
```

---

## Pipeline Architecture (LangGraph)

The pipeline is a linear 7-node StateGraph with checkpointing (MemorySaver):

```
discover → filter → analyze → tailor → cover_letter → email → apply
```

### State (PipelineState)

```python
class PipelineState(TypedDict):
    config: dict              # Snapshot of current config
    jobs: list[dict]          # Job listings being processed
    raw_jobs_count: int
    filtered_jobs_count: int
    current_job_index: int
    current_job: Optional[dict]
    master_resume: Optional[dict]
    tailored_resume: Optional[dict]
    verifier_report: Optional[dict]
    cover_letter: Optional[str]
    email_draft: Optional[str]
    email_contacts: list[dict]
    humanization_score: Optional[float]
    application_results: list[dict]
    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    run_id: Optional[str]
    dry_run: bool
    stage: str
```

### Node Details

| Node | Component | What It Does | LLM Calls |
|------|-----------|-------------|-----------|
| **discover** | InternshalaScraper | Scrapes 3 pages per keyword+location, enriches with detail page JSON-LD | 0 |
| **filter** | Post-filter logic | Dedup (DB + in-memory), paid check (≥₹5000), location (Remote/Bangalore), keyword match, recency sort (newest first) | 0 |
| **analyze** | JDAnalyzer | Extracts required_skills, nice_to_have, top_keywords from JD using LLM | 1 per job |
| **tailor** | ResumeTailor + ResumeVerifier | Rewrites summary, reorders skills, selects 3-4 projects, verifies against source (score < 60 → retry, max 2) | 1 per job (+ retries) |
| **cover_letter** | CoverLetterGen | Two-pass: LLM draft → humanization (cliché strip, hedging removal, sentence variety) | 1 per job (up to 3 regens) |
| **email** | EmailFinder + CoverLetterGen | Finds hiring manager emails via Hunter.io, generates cold email, saves to DB for approval | 1 per job |
| **apply** | InternshalaSubmitter | CDP browser → navigate → fill → upload resume → submit → screenshot | 0 |

### Key Pipeline Behaviors

- **Rate limiter**: Token-bucket (30 calls/min) shared across all LLM-calling nodes
- **Dedup**: Only skips jobs that have been **applied to** (status = applied/submitted), NOT just jobs in DB
- **Recency**: Parses relative dates ("3 days ago", "1 week ago") → sorts newest first
- **Checkpointing**: LangGraph MemorySaver — survives crashes mid-pipeline
- **Structured logging**: Every node logs timing, item count, error count

---

## Configuration (.env)

### Required
```
OPENCODE_GO_API_KEY=sk-...        # OpenCode Go subscription API key
OPENCODE_GO_MODEL=deepseek-v4-flash # LLM model
OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1
```

### Optional — Discovery
```
SEARCH_KEYWORDS=["python","java","backend","software development","full stack"]
SEARCH_LOCATIONS=["Remote","Bangalore"]
MIN_STIPEND_INR=5000
```

### Optional — Email Outreach
```
HUNTER_API_KEY=...                 # Hunter.io (50 free searches/month)
GMAIL_SENDER_EMAIL=...             # Gmail address to send from
GMAIL_CLIENT_SECRET_PATH=...       # Google Cloud OAuth client_secret.json
```

### Optional — Enrichment
```
NAUKRI_APIFY_TOKEN=...             # Currently dead actor — not used
```

---

## Data Models

### JobListing
Stores discovered jobs from Internshala. Key fields: title, company, location, stipend_min/max, stipend_raw, skills (JSON), analysis (JSON), description (from detail page enrichment), source, url, posted_at, posted_at_date (for recency sorting), is_paid, is_remote.

### Application
Tracks application state per job. Fields: job_id, status (discovered/applied/submitted/email_drafted/email_sent), tailored_resume_path, cover_letter_path, email_sent, email_sent_at, email_contacts (JSON), email_draft_path, portal_submitted, verifier_score, humanization_score.

### Resume
Master resume data. Fields: name, email, phone, location, summary, education (JSON), skills (JSON dict by category), projects (JSON), additional (JSON). Canonical source: `profile/resume.json`.

### EmailLookup
Cache for Hunter.io domain lookups. Fields: domain (unique), emails (JSON), cached_at.

---

## CLI Commands

```bash
internapply doctor               # System check (all API keys, files, DB)
internapply resume init [file]   # Parse JS generator → profile/resume.json
internapply resume show          # Display current resume
internapply resume add-skill "Cat: Skill"
internapply resume add-project "Name" --description "B1;B2" --tech "Stack"
internapply resume edit          # Open in $EDITOR
internapply discover             # Find internships (--dry-run, --max-jobs)
internapply run                  # Full pipeline (--dry-run, --max-jobs, --from-stage)
internapply status               # Dashboard of jobs/applications/emails
internapply email setup          # Gmail OAuth authentication
internapply email list           # Show pending email approvals
internapply email send --all --approve  # Actually send emails
internapply email export-token --raw    # Export Gmail token for CI
```

---

## Tests (63 tests)

| Test File | Tests | What It Verifies |
|-----------|-------|-----------------|
| test_verifier.py | 12 | Clean resume passes (100), FakeProject detected, date normalization, education mismatch, metrics, clichés |
| test_scorer.py | 6 | Deterministic scoring, keyword match, format scoring, title match |
| test_pipeline.py | 10 | State initialization, graph topology (7 nodes), error accumulation |
| test_database.py | 8 | Migration V1+V2, schema version, idempotent init |
| test_models.py | 6 | JobListing, Application, Resume creation + serialization |
| test_internshala.py | 5 | Stipend parsing (range, unpaid, single), URL building |
| test_config.py | 6 | Defaults, env overrides, list parsing, immutability |
| test_naukri.py | 2 | Salary parsing (LPA→monthly) |
| test_internshala_scraper.py | 5 | Stipend parsing edge cases |

---

## External Dependencies / API Keys

| Service | Cost | Usage | Key In .env |
|---------|------|-------|-------------|
| **OpenCode Go** | Included with subscription | All LLM calls (JD analysis, tailoring, cover letters) | `OPENCODE_GO_API_KEY` |
| **Hunter.io** | Free tier (50/mo) | Find hiring manager emails from company domains | `HUNTER_API_KEY` |
| **Gmail API** | Free | Send cold emails with Gmail.send scope only | `GMAIL_*` |
| **GitHub API** | Free | Fetch profile data (public repos, languages) | No key needed |
| **Internshala** | Free | Job listings + application submission | No key needed |
| **Naukri** | Free via Apify (dead) | No longer working | `NAUKRI_APIFY_TOKEN` (dead) |

---

## How Each Component Works

### LLM Client (llm.py)
Wrapper around OpenAI-compatible OpenCode Go API. Supports sync + async calls. Retry with exponential backoff (3 retries, 2s base + jitter). Default max_tokens=16384 (increased for deepseek thinking model which uses ~1000+ reasoning tokens per call).

### Internshala Scraper (discovery/internshala.py)
HTTP GET + BeautifulSoup — no Playwright needed for listings. Scrapes 3 paginated pages per keyword+location. After filters pass, fetches **detail page** for each job to extract JSON-LD `JobPosting` data (description, company, stipend, skills). Returns 46+ cards per keyword.

Filters applied: stipend ≥ ₹5000, location (Remote/Bangalore), keyword match (title contains significant word from search terms).

### Resume Tailor (resume/tailor.py)
Takes master resume JSON + JD analysis → LLM prompt with 8 strict rules (no fabrication, student context, reorder only). Output: summary, skills_reordered, projects (selected 3-4 best), education. Verifier gate retries up to 2 times if score < 60.

**CRITICAL**: Prompts explicitly state "B.Tech student with hobby/open-source projects — NOT professional experience."

### Verifier Gate (resume/verifier.py)
Fully deterministic — NO LLM calls. 6 checks:
1. Project names exist in source
2. Skills exist in source (case-insensitive substring)
3. Dates normalized to YYYY-MM → match exists
4. Numeric metrics (40%, $2M, 1000+) exist in source
5. Education: degree, institution, gpa each match source
6. AI clichés flagged as warnings (18 patterns)

Score = max(0, 100 - violations×20). Score ≥ 60 = pass.

### Cover Letter + Humanization (resume/cover_letter.py)
Two-pass: LLM draft (temp=0.7) → humanization pass. Humanization removes: clichés, robotic patterns ("I would like to request" → "Could we"), hedging ("just", "maybe", "perhaps"). Score: 5 criteria × 20pts each (no clichés, varied sentence starters, no hedging, natural phrasing, word count 80-120). Regenerates if score < 80 (max 3 attempts).

### Resume Renderer (resume/renderer.py)
Generates professional ATS-optimized DOCX using python-docx. Single-column, Arial 9.5pt, 0.55" margins. Shows: top 10 skills only, max 4 projects with 2 bullets each, 1 page enforced. No tables, no graphics, no columns.

### Gmail Sender (outreach/sender.py)
OAuth2 with `gmail.send` scope only. Token encrypted at rest via cryptography.fernet. Supports file attachments via MIME multipart. Rate limited to 20/day. Clenup: strips stray "Subject:" lines from body, normalizes line breaks.

### Email Finder (outreach/email_finder.py)
Skips known job board domains (internshala.com, linkedin.com, etc.) — uses company name instead. Drops legal suffixes (Private Limited → domain). Caches results in DB. Filters by position keywords (recruiter, hiring, talent, hr, manager, head, director, vp, chief). Sorts by seniority, returns top 3.

### CDP Browser (apply/browser.py)
Probes ports 9222-9242 for existing Chrome, or accepts configured CDP_URL. Launches with random port, bound to 127.0.0.1 only (security). Falls back to headless Playwright if no Chrome found.

### Internshala Auto-Apply (apply/internshala.py)
Requires logged-in Chrome via CDP. Steps: navigate → click Apply Now (12+ selectors) → fill cover letter → upload resume PDF → detect screening questions (skip) → submit → screenshot. Max 5/session, 3-5min delays, 15/day limit.

---

## Key Design Decisions (with Research Basis)

| Decision | Research | Implementation |
|----------|----------|---------------|
| **No LinkedIn auto-apply** | H1 falsified — LSTM detection, 48-signal fingerprinting, permanent bans | LinkedIn discovery only (guest endpoint) |
| **LLM + verifier gate** (not templates) | H3 falsified — +41% ATS score with LLM; 2.48-5.36 hallucinated items/resume | LLM generates → deterministic verifier checks every claim |
| **Internshala primary target** | H2 survived — HTTP-only scraping works, weak bot detection | HTTP for listings, Playwright only for submission |
| **Post-hoc stipend filtering** | H5 survived — platform filters are "advisory" | Parse raw text → INR numeric → re-filter |
| **LangGraph orchestration** | H4 provisionally falsified — 99.7% reliability | StateGraph with MemorySaver checkpointing |
| **DOCX > PDF for ATS** | Workday/Greenhouse/Lever parse DOCX at 96-100% vs PDF 92-98% | python-docx generator |
| **No resume in first email** | Cold emails with attachments get lower response | Offer to share, attach only after reply — **EXCEPT for internships** where attached is standard |
| **Email approval gate** | Prevent accidental sends | `--approve` flag required |
| **Encrypted Gmail token** | Security | cryptography.fernet + machine-specific seed |
| **Relative date parsing** | Internshala uses "3 days ago", "Few hours ago", "1 month ago" | Regex patterns → datetime.date → sort newest-first |

---

## GitHub Actions CI/CD

**Daily workflow** (`.github/workflows/daily-run.yml`):
- Schedule: daily at 03:17 UTC (08:47 IST)
- Timeout: 30 min
- Downloads SQLite DB artifact from last run → runs discovery + analysis → uploads updated DB
- Skips auto-apply in CI (needs logged-in Chrome)
- Creates GitHub Issue on failure

**Secrets required**:
- `OPENCODE_GO_API_KEY`, `HUNTER_API_KEY`, `GMAIL_SENDER_EMAIL`, `GMAIL_CLIENT_SECRET_PATH`, `NAUKRI_APIFY_TOKEN`
- `GMAIL_TOKEN_JSON` (generated via `internapply email export-token --raw`)
- `INTERNSHALA_SESSION_JSON` (optional, for auto-apply)

---

## Known Issues / Tech Debt

1. **Naukri scraper** — Apify actor `droidmaster/naukri-jobs-feed` is dead (404). HTTP scraping impossible (Next.js SPA + Akamai). Remove from pipeline.
2. **Internshala card parsing** — HTML structure changes frequently. Current text-based parsing is resilient but imperfect. Some titles/companies still mis-parsed.
3. **Empty descriptions** — If detail page enrichment fails (timeout/network), job gets skipped during analysis. No retry mechanism.
4. **LLM token cost** — Deepseek uses thinking tokens (1000+ per call). Each pipeline run makes ~15 LLM calls = ~15K-30K thinking tokens + output.
5. **Resume CGPA** — Needs manual update in profile/resume.json via `internapply resume edit`.
6. **GMAIL_TOKEN_JSON not in CI** — Needs manual export + secret setup.
7. **All 5 API keys checked by doctor** — System check command shows green/red for each.

---

## How to Extend

### Add a new job source
1. Create `internapply/discovery/newsource.py` with async `search(keywords, locations) → list[JobListing]`
2. Add to `pipeline/nodes.py` `discover_jobs` node (follow Internshala pattern)
3. Add to CLI `discover` command if needed

### Add a new resume section
1. Update `profile/resume.json` with new fields
2. Update `internapply/resume/renderer.py` `render_resume()` to include it
3. The verifier will automatically check any new fields

### Modify the LLM prompt
- JD analyzer prompt: `internapply/resume/analyzer.py` `_BUILD_LLM_PROMPT()`
- Resume tailor prompt: `internapply/resume/tailor.py` (embedded in `tailor()` method)
- Cover letter prompt: `internapply/resume/cover_letter.py` `_build_draft_prompt()`
