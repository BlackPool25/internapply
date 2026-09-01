---
name: resume-tailor
description: "On-demand resume tailor — 1 LLM call cached ₹0.008, WARN@80 verifier, deterministic DOCX 96.7% ATS. Invoke via /tailor or skill:resume-tailor per JD (not pipeline). Handles jd_hash cache, B.Tech hobby projects NOT professional, volatile-stripped dedup."
license: MIT
---

# Resume Tailor Skill — On-Demand WARN@80 + Cache + DOCX

On-demand per-JD resume tailoring. **Not in pipeline** — invoke explicitly via `/tailor` or `skill:resume-tailor`.

## Prerequisites

1. **Docker** installed (if using API) or local Python `uv run`
2. **`.env`** has `OPENCODE_GO_API_KEY` for real LLM (mock otherwise)
3. **`profile/resume.json`** exists — source of truth, B.Tech AI/ML 9.36 + B.Sc CS 8.91, 10 projects. Assert `load_resume_json()` is not None before tailor.

## Hard Preconditions

Before tailoring, verify ALL:

1. **Resume exists**: `profile/resume.json` present. If not: `Run internapply resume init` — assert `load_resume_json()` is not None.
2. **JD provided**: `--jd-text` or `--jd-file` or stdin. Empty JD → 422.
3. **Cache dir writable**: `data/tailor_cache.json` creatable.

If any fails, DO NOT proceed.

## Skill Invocation

```bash
/tailor
skill:resume-tailor
python scripts/tailor.py --job-title "Backend Intern" --company Acme --jd-file jd.txt --canonical-id abc123
python scripts/tailor.py --job-title "Backend Intern" --company Acme --jd-text "We need Python FastAPI..."
cat jd.txt | python scripts/tailor.py --job-title "Backend Intern" --company Acme
```

Not `internapply research` pipeline — pipeline truncated to 3 nodes, LLM moved to skill only.

## Workflow

```
input job_title,company,jd_text,canonical_id
  → assert load_resume_json() is not None
  → jd_hash via backend/app/discovery/hash_utils.jd_hash (volatile stripped, %→percent, HTML stripped)
  → check data/tailor_cache.json key jd_hash — hit→0 LLM return cached tailors_resume+score+docx_path
  → miss: 1 LLM call (mini) cached ₹0.008 — prompt includes "B.Tech hobby projects NOT professional"
  → ResumeVerifier.verify + normalize_metric (cut/reduced 40% same via regex) + voltile stripped
  → score badges: >80 green pass, 70-80 yellow WARN (not 422) for first 30 JDs, <70 red with verifier_issues
  → if score <70 → 422 with verifier_issues (hard block)
  → if 70-80 and calibration (<30 entries) → WARN yellow badge + warning, return DOCX anyway
  → after 30-JD calibration flip WARN→hard 422
  → render via internapply/resume/renderer.py python-docx deterministic DOCX (96.7% ATS parse, CVCraft 6-platform: Workday 96/Taleo97/Greenhouse98/Lever98) — single-column, no table, sorted keys
  → ats-reader heading/list/table check: block multi-col/table (w:tbl, w:cols num>1) → hard fail
  → save to applications/{canonical_id}/resume.docx (or jd_hash[:8] if no canonical_id)
  → update cache: data/tailor_cache.json {jd_hash: {tailored_resume, score, verifier_issues, docx_path, badge, cost}}
  → POST idempotency via cache key jd_hash (same JD → same doc)
```

## Cost

- 1 LLM call per unique JD (mini): **₹0.008**
- Cache hit: **₹0.00**, 0 LLM
- Calibrated via `data/tailor_cache.json`

## WARN@80 Logic

| Score | Badge | <30 JDs | ≥30 JDs |
|-------|-------|---------|---------|
| >80   | green | pass    | pass    |
| 70-80 | yellow| WARN not 422 (return DOCX) | hard 422 |
| <70   | red   | 422     | 422     |

`normalize_metric("cut latency 40%") == normalize_metric("reduced time by 40 percent")` via `internapply/resume/verifier.py:normalize_metric` (regex %→percent, synonym map cut→reduce, time→latency, stopwords dropped).

## Cache

`data/tailor_cache.json` — key `jd_hash` (sha256 normalized canonical JD — volatile stripped, percent synonyms unified). Must NOT call LLM if hit.

```json
{
  "a1b2...": {"tailored_resume": {...}, "score": 100, "badge": "green", "docx_path": "applications/.../resume.docx"}
}
```

Calibration count = number of non-`_` keys; <30 → WARN mode.

## DOCX

- `internapply/resume/renderer.py:render_resume` — python-docx, 1 col, no `w:tbl`, deterministic (sorted keys, fixed core props 2025-01-01)
- `internapply/resume/renderer.py:ats_reader_check` — blocks multi-col/table, verifies headings/lists
- ATS: 96.7% parse, CVCraft 6-platform Workday 96/Taleo97/Greenhouse98/Lever98

## Profile

`profile/resume.json` is source of truth via `internapply/resume/parser.py:load_resume_json()`. Assert not None before tailor. Contains 10 projects; template dir has ATS cover.

## Commands

| Command | Effect |
|---------|--------|
| `python scripts/tailor.py --help` | show args (must grep `tailor`) |
| `python scripts/tailor.py --job-title X --company Y --jd-file f --canonical-id id` | tailor + cache + DOCX |
| `python scripts/tailor.py --clear-cache` | reset calibration |

## Related Paths

| Resource | Path |
|----------|------|
| Skill definition | `.opencode/skills/resume-tailor/SKILL.md` |
| CLI | `scripts/tailor.py` |
| Verifier | `internapply/resume/verifier.py` |
| Renderer | `internapply/resume/renderer.py` |
| Cache | `data/tailor_cache.json` |
| Parser | `internapply/resume/parser.py:load_resume_json()` |
| Hash | `backend/app/discovery/hash_utils.py:jd_hash` |
| Templates | `.opencode/skills/resume-tailor/templates/` |
| Evidence | `.omo/evidence/task-13-skill.md` |
