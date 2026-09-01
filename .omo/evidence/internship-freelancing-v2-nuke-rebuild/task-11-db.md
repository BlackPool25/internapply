# Task 11 — DB Migration: Alembic + canonical_id 64 UNIQUE + dead_letters

## Summary
Postgres 16 primary via `backend/alembic/` (reuse, not `backend/app/alembic/` duplicate).  
Engine pool `10/10` with `AsyncAdaptedQueuePool`, assert `(10+10)*2=40 <100` (max_connections).  
Hash dedup: `canonical_id VARCHAR(64) UNIQUE` (sha256 64 hex, not 128), `jd_hash VARCHAR(64)` indexed, `simhash BIGINT`, `etag VARCHAR(255)`, `change_log JSONB`, `source_ats VARCHAR(32)`, `last_seen_at TIMESTAMPTZ` indexed for cursor fallback `updated_at → last_seen_at → posted_at_date`.  
`dead_letters(source VARCHAR(32), url VARCHAR(2048), UNIQUE(source,url))` + `next_retry_at` index.  
`batch_queue` orphan archived/dropped via idempotent migration; `pipeline_runs` retained for observability.

## Files
- `backend/alembic/env.py` — async (`async_engine_from_config` + `NullPool` + `run_sync`), reads `DATABASE_URL` env.
- `backend/alembic.ini` — `sqlalchemy.url = postgresql+asyncpg://internapply:changeme@localhost:5432/internapply` placeholder (overridden by env).
- `backend/alembic/versions/0002_add_hash_dedup.py` — adds 7 columns + dead_letters + drops batch_queue (idempotent, offline `--sql` safe). Revision `0002_add_hash_dedup` → `0001_initial_schema`.
- `backend/app/database.py` — pool 10/10 already, verified `AsyncAdaptedQueuePool`.
- `backend/app/models.py` — `JobListing.canonical_id String(64) UNIQUE indexed`, `jd_hash 64 indexed`, `simhash BigInteger`, `etag 255`, `change_log JSONB`, `source_ats 32`, `last_seen_at TZ indexed`, `DeadLetter` model + `get_job_by_canonical_id`, `cursor_value` fallback; `BatchQueue` nuked (no grep hit).
- `internapply/database.py` — SQLite CLI mirror: same hash fields + `ORMDeadLetter` + V3 migration (Postgres primary documented).
- `.env.example` — Postgres primary note.
- `tests/test_database.py` — 8 tests (4 new + 4 CLI mirror) via in-memory SQLite.

## Verification
```bash
alembic -c backend/alembic.ini history
# 0001_initial_schema -> 0002_add_hash_dedup (head)
alembic -c backend/alembic.ini upgrade head --sql  # offline SQL generates ALTERs + dead_letters + DROP batch_queue
grep -q "canonical_id.*64" backend/app/models.py && echo ok
! grep -q "String(128)" backend/app/models.py && echo ok
! grep -q "batch_queue" backend/app/models.py && echo nuked
python -c "from sqlalchemy.ext.asyncio import create_async_engine; from sqlalchemy.pool import AsyncAdaptedQueuePool; e=create_async_engine('postgresql+asyncpg://u:p@localhost/db', pool_size=10, max_overflow=10, poolclass=AsyncAdaptedQueuePool); assert e.pool.size()==10"
pytest tests/test_database.py -q  # 8 passed
# - test_canonical_id_unique_64 duplicate → IntegrityError
# - test_dead_letters_unique same (source,url) → IntegrityError
# - test_jd_hash_primary_skip same jd_hash → skip
# - test_128_would_waste String(64) not 128
docker compose -f docker/docker-compose.yml config | grep postgres:16
```

## Ponytail
Kept `internapply/database.py` SQLite mirror idempotent V3 (no new deps), reused `backend/alembic/` (no duplicate), stdlib sha256 only. Skipped custom cache, kept minimal diff.

## Commit
`feat(db): Alembic canonical_id 64 UNIQUE + jd_hash + dead_letters + pool 10/10 (Momus B4)`
