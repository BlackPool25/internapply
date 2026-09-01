# Task 2 — pyproject deps + hash_utils 64-hex (Evidence)

## Changes
- `pyproject.toml` added: asyncpg>=0.29.0, alembic>=1.13.0, redis>=5.0.0, tenacity>=8.2.0, structlog>=24.1.0, prometheus-client>=0.20.0, asgi-correlation-id>=2.0.0, prometheus-fastapi-instrumentator>=6.0.0, arq>=0.26.3, httpx bumped 0.25→0.27.0 (http2=False, no extra). Kept langgraph, python>=3.11, ruff py311. No celery.
- `docker/requirements.txt` mirrored same 8 deps.
- `backend/app/discovery/hash_utils.py` + `internapply/discovery/hash_utils.py` mirror: canonical_id 64 hex sha256, jd_hash volatile stripped (dates/views/csrf), percent synonym 40%==40 percent, simhash64 pure-python 64-bit Hamming ≤3, etag advisory, diff_change_log volatile-excluded, normalize_metric, HASH_SALT lazy via config/env fallback "internapply-v1".
- `tests/test_hash_utils.py` 4 tests: 64hex, volatile stripped, metric synonym, cross-company not merge.

## Ponytail ladder
- Stdlib hashlib.sha256 only, no new deps. BS.get_text only if HTML detected, else regex fallback. Copy mirror not shared package.

## Verification
```
python -m pip check
No broken requirements found.

python -c "import asyncpg, alembic, redis, tenacity, structlog, prometheus_client; print('deps ok')"
deps ok

python -c "from backend.app.discovery.hash_utils import canonical_id, jd_hash; assert len(canonical_id('Acme','Backend Intern','Remote','https://x'))==64; assert jd_hash('<p>Hello  2024-08-01</p>')==jd_hash('hello'); assert jd_hash('Role 40% bonus')==jd_hash('Role 40 percent bonus')"
hash ok

pytest tests/test_hash_utils.py -q
4 passed

grep -r celery pyproject.toml → 0
grep -r httpx\[http2\] pyproject.toml → 0
grep 64 hex check: canonical_id len 64 not 128
```

## Skipped
- Config HASH_SALT formal field (Todo 3), alembic migration (Todo 11), celery nuke already absent.
