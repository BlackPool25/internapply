# Task 3 — Config divergence fix

## What changed
- internapply/config.py: added HASH_SALT, SIMHASH_THRESHOLD, VERIFIER_MIN_SCORE, HIRIST_ENABLED, UNSTOP_ENABLED, ARBEITNOW_ENABLED, REMOTIVE_ENABLED, THEMUSE_ENABLED, JOBICY_ENABLED, WREQ_SIDECAR_URL, VOLLNA_RSS_URL + lazy @property ats_boards (warn if <50, [] if missing) + BOARD_SOURCE log in model_post_init. Kept frozen=True, no Field(default_factory open).
- backend/app/config.py: mirrored same fields + ats_boards property, database_url default now postgres:5432 with comment about docker-compose override.
- .env.example: documented HASH_SALT, thresholds, flags, DATABASE_URL/REDIS_URL/ENV.
- tests/test_config.py: added test_lazy_boards_no_crash, test_new_defaults, test_boards_validator_warn.

## Verification
- `python -c "from internapply.config import get_config; c=get_config(); assert c.HASH_SALT=='internapply-v1'; print(c.ats_boards[:2])"` → 2 boards, count 100.
- tmpdir chdir no file → [] no crash, 1 board <50 → warn not crash.
- `from backend.app.config import settings; assert settings.HASH_SALT=='internapply-v1'` → ok, ats_boards 100.
- `pytest tests/test_config.py -q` → 8 passed.
- grep HASH_SALT both files ok, no default_factory open.

## Ponytail
Skipped per-field env validators, kept simple defaults. Add stricter validation when needed.
