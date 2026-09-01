# Secrets Audit — 2026-09-01

**Verdict: PASS — no real secrets in git history or tracked files. All keys are placeholders or `${{ secrets.* }}`. `.env` never committed. One minor `.gitignore` hardening applied.**

## 1. Scope

| Item | Value |
|------|-------|
| Repo | `git@github.com:BlackPool25/internapply.git` |
| Commits scanned | 56 (`git log --all --oneline \| wc -l`) |
| Branch | `main` (HEAD `10e0b52`) |
| Tools | manual `git log -p` grep, `grep -R`, `git ls-files`, `git check-ignore`, `git log --all --patch -- .env` (gitleaks/trufflehog not installed — manual entropy scan used) |
| Secrets in scope | `OPENCODE_GO_API_KEY` (`sk-…`), `HUNTER_API_KEY`, `GMAIL_*` (`GMAIL_TOKEN_JSON`, `GMAIL_TOKEN_PASSPHRASE`, `credentials.json`), `DB_PASSWORD`, `REDIS_URL`, generic `ghp_*`, `AKIA*`, `sk-[A-Za-z0-9]{20,}` |

## 2. Checks

| # | Check | Command | Result | Status |
|---|-------|---------|--------|--------|
| 1 | `.env` is gitignored | `git check-ignore -v .env` → `.gitignore:2:.env .env` | ignored | **PASS** |
| 2 | `.env` not tracked | `git ls-files \| grep -q "^\.env$"` → no match; only `.env.example` tracked | not tracked | **PASS** |
| 3 | `.env` never committed in history | `git log --all --patch -- .env` → empty; `git log --all --oneline -- .env` → empty; `git log --all --diff-filter=A -- .env` → empty | never added | **PASS** |
| 4 | `.env.example` placeholders only | `cat .env.example` → `OPENCODE_GO_API_KEY=` (empty), `DATABASE_URL=…changeme…`, `HUNTER_API_KEY=` empty; no `sk-` value | placeholder | **PASS** |
| 5 | `docker/.env.example` placeholders only | `cat docker/.env.example` → `DB_PASSWORD=changeme`, `OPENCODE_GO_API_KEY=sk-your-key-here` | placeholder+masks | **PASS** |
| 6 | Local `.env` placeholders | `cat .env` → `DB_PASSWORD=changeme`, `OPENCODE_GO_API_KEY=sk-your-key-here`, `HUNTER_API_KEY=` | placeholder (not a live key) | **PASS** |
| 7 | History grep `OPENCODE_GO_API_KEY\|HUNTER_API_KEY\|GMAIL\|DB_PASSWORD` | `git log --all -p \| grep -E "OPENCODE_GO_API_KEY\|HUNTER_API_KEY\|GMAIL"` → 15 hits, all docs/config refs + `${{ secrets.* }}` or empty placeholder; `*_API_KEY=           # Your …` | no real value | **PASS** |
| 8 | History grep `sk-[A-Za-z0-9]{20,}` / `ghp_` / `AKIA` | `git log --all -p \| grep -E "sk-[a-zA-Z0-9]{20,}\|ghp_[A-Za-z0-9]{30,}\|AKIA[0-9A-Z]{16}"` → 0 hits | no high-entropy key | **PASS** |
| 9 | Working tree `sk-` scan | `grep -R "sk-" --include="*.py" --include="*.md"` → only `sk-****` masked docs (`ARCHITECTURE.md: sk-...`, `SETUP.md: sk-...`, test `sk-test-key-12345`), plus vendored `.venv` | masked/test only | **PASS** |
| 10 | Working tree `OPENCODE_GO_API_KEY` scan | `grep -R "OPENCODE_GO_API_KEY" --include="*.py" --include="*.md" --include="*.yml"` → code refs (`config.py`, `llm.py`, `doctor.py`), env var wiring (`docker-compose.yml: ${OPENCODE_GO_API_KEY}`, `daily-run.yml: ${{ secrets.OPENCODE_GO_API_KEY }}`), docs — no literal key | reference only | **PASS** |
| 11 | `HUNTER_API_KEY` / `GMAIL_TOKEN_JSON` history | `git log --all -p \| grep -i "GMAIL_TOKEN"` → only code/docs + `${{ secrets.GMAIL_TOKEN_JSON }}`; `HUNTER_API_KEY` only code/docs | no real token | **PASS** |
| 12 | `password`/`secret` history | `git log --all -p \| grep -i "password\|secret"` → `DB_PASSWORD` docs + `POSTGRES_PASSWORD: test` (CI dummy) + `secrets.*` | `test` is CI dummy, not a real password | **PASS** |
| 13 | `applications/browser_session.json` not tracked | `git ls-files \| grep applications` → empty; `git check-ignore -v applications/browser_session.json` → `.gitignore:21:applications/` | ignored, never committed | **PASS** |
| 14 | `*.db` / `*.sqlite3` ignored | `.gitignore` has `*.db`, `*.sqlite3`; `git ls-files \| grep "\.db"` → empty | PASS | **PASS** |
| 15 | `data/` ignored | `.gitignore:20:data/`; `git check-ignore -v data/tailor_cache.json` → `data/` | PASS (see §4 anomaly) | **PASS** |
| 16 | `*.token` / `credentials.json` ignored | `.gitignore` has `*.token`, `credentials.json`; no such files tracked | PASS | **PASS** |
| 17 | CI secrets are `${{ secrets.* }}` | `cat .github/workflows/daily-run.yml` → `OPENCODE_GO_API_KEY: ${{ secrets.OPENCODE_GO_API_KEY }}`, `HUNTER_API_KEY: ${{ secrets.HUNTER_API_KEY }}`, `GMAIL_TOKEN_JSON: ${{ secrets.GMAIL_TOKEN_JSON }}` — no literals | PASS | **PASS** |
| 18 | Docker compose uses env substitution | `docker/docker-compose.yml` → `OPENCODE_GO_API_KEY: ${OPENCODE_GO_API_KEY}`, `POSTGRES_PASSWORD: ${DB_PASSWORD:?error}` — no literals | PASS | **PASS** |

## 3. Evidence snippets (masked)

```
# .gitignore (now)
# Environment
.env
.env.local
...
data/
applications/
*.token
credentials.json
*.enc
data/*.enc

# .env.example
OPENCODE_GO_API_KEY=           # Your OpenCode Go API key (get from opencode account settings)
DATABASE_URL=postgresql+asyncpg://internapply:changeme@postgres:5432/internapply
HUNTER_API_KEY=                # https://hunter.io — free tier: 50 searches/month, X/50 counter

# docker/.env.example
DB_PASSWORD=changeme
OPENCODE_GO_API_KEY=sk-your-key-here   # placeholder, not a live key

# git ls-files | grep .env
.env.example

# git log --all --patch -- .env
(empty — .env never committed)

# git log --all -p | grep -E "sk-[a-zA-Z0-9]{20,}" | head
(empty — no high-entropy sk- key in history)

# grep -R "OPENCODE_GO_API_KEY" (working tree, excerpt)
internapply/config.py:    OPENCODE_GO_API_KEY: str = Field(default="", …)
docker/docker-compose.yml:      OPENCODE_GO_API_KEY: ${OPENCODE_GO_API_KEY}
.github/workflows/daily-run.yml:          OPENCODE_GO_API_KEY: ${{ secrets.OPENCODE_GO_API_KEY }}
```

## 4. Findings & remediation

### Clean

- **No real API keys, tokens, or passwords in any of 56 commits or in any tracked file.** All references are placeholder (`changeme`, `sk-your-key-here`, empty), masked doc (`sk-...`), test dummy (`sk-test-key-12345`), or `${{ secrets.* }}` / `${VAR}` indirection.
- `.env` is correctly gitignored and has never been committed. Verification `git log --all -p | grep -i "sk-.*"` returns empty for real keys.

### Minor hardening (applied)

- Added `*.enc` + `data/*.enc` to `.gitignore` to cover `data/gmail_token.enc` (encrypted OAuth token persisted by `internapply/outreach/sender.py`). Previous `.gitignore` had `*.token` + `credentials.json` but not `*.enc`.
  - Diff: `+*.enc` + `+data/*.enc` under `# Tokens`.
  - No commit needed beyond this audit — change is in working tree and should be committed as `chore(security): ignore encrypted token files`.

### Informational (no fix required, but note for next PR)

- `profile/resume.json` is tracked and contains PII (name, email `sh****@gmail.com`, phone `+91 78******81`). Not a secret, but if repo becomes public, consider gitignoring and shipping `profile/resume.json.example` instead. Currently `git check-ignore -v profile/resume.json` → not ignored; adding `profile/resume.json` to `.gitignore` would require `git rm --cached` — do not do silently, ask owner.
- `data/tailor_cache.json` is tracked (`{}`) despite `data/` in `.gitignore`. It was force-added in `7cacf67`. History shows `+{}` only, no secret. Recommend `git rm --cached data/tailor_cache.json` and keep it untracked (cache belongs in `.gitignore`), but not urgent — file is empty.
- `gitleaks` / `trufflehog` not installed in this environment. Recommend adding prevention (see §5).

## 5. Prevention — recommended next steps

| Action | How | Priority |
|--------|-----|----------|
| **CI gitleaks** | Add to `.github/workflows/test.yml`: `gitleaks/gitleaks-action@v2` with `gitleaks detect --source . --verbose` (fail on leaks). | High |
| **Pre-commit hook** | Add `.pre-commit-config.yaml` with `gitleaks` or `detect-secrets` (`- repo: https://github.com/gitleaks/gitleaks — rev: v8.x — hooks: id: gitleaks`). Run `pre-commit install`. | High |
| **.gitleaksignore** | If needed, allowlist `sk-test-key-12345` / `sk-your-key-here` so CI doesn't false-positive on placeholders/tests. | Medium |
| **Rotate if ever leaked** | If a real `sk-` key was ever committed, rotate at https://opencode.ai → revoke old, update `OPENCODE_GO_API_KEY` in local `.env` and GitHub Secrets. History purge requires `git filter-repo` or BFG + force push — **ask owner before force push**. Not needed today (clean). | — |
| **Keep `.env.example` as template** | Ensure `OPENCODE_GO_API_KEY=changeme` or empty, never a real value; CI uses `secrets.*` only. Already correct. | — |

## 6. How to re-verify

```bash
# .env not tracked
git ls-files | grep -q "^\.env$" && echo "FAIL tracked" || echo "PASS not tracked"
git check-ignore -v .env

# .env never in history
git log --all --patch -- .env | head
git log --all --oneline -- .env

# No real key in history (should be empty or only masked)
git log --all -p | grep -E "OPENCODE_GO_API_KEY|HUNTER_API_KEY|GMAIL" | head -20
git log --all -p | grep -E "sk-[a-zA-Z0-9]{20,}" | head

# Working tree has only placeholders / masked
grep -R "OPENCODE_GO_API_KEY" --include="*.py" --include="*.md" --include="*.yml" .
grep -R "sk-" --include="*.py" --include="*.md" | grep -v ".venv" | grep -v "node_modules"

# Placeholders
grep -E "changeme|sk-your-key" .env.example docker/.env.example
```

## 7. Commit

- `.gitignore` hardening (`*.enc`, `data/*.enc`) — pending commit:
  ```
  git add .gitignore .omo/evidence/secrets-audit.md
  git commit -m "chore(security): ignore encrypted token files + secrets audit PASS"
  ```
- No history rewrite needed. Do **not** force push.

---
*Audit by Sisyphus-Junior, 2026-09-01. Evidence at `.omo/evidence/secrets-audit.md`.*
