# Task 10 — arq queue + Beat cron + circuit breaker + dead letter + observability

## Summary
- Enhanced `backend/app/worker.py` with per-source arq tasks (greenhouse, lever, ashby, smartrecruiters, hirist, unstop, internshala, free_apis, jobspy, freelance) + `discover_all` fan-out, tenacity `wait_exponential_jitter(multiplier=0.5,max=30)` `stop_after_attempt(3)` retry only 429/502/503/504+timeouts, never 401/403/404/422, `Retry-After` parse (seconds or HTTP-date) clamp `max_wait=30`, Hirist `Idempotency-Key` header, hourly cron `hour={*range(24)} minute=0 unique=True timeout=600 keep_result=0`.
- Created `backend/app/discovery/circuit.py` with `CircuitBreaker` using `Redis SETNX breaker:{source} EX 60` `fail_max=5 reset_timeout=60` exclude 404, in-memory fallback, helpers `check_breaker`, `add_dead_letter`.
- Created `backend/app/observability/metrics.py` with `structlog` JSON + `prometheus_client` `Counter(discovery_jobs_total{source,status})` + `Histogram(discovery_latency_seconds, buckets=(0.1,0.5,1,2,5,10,30))` + `Gauge(queue_depth)` + `parse_retry_after` clamp + `GET /health/discovery` state (last_run, latency_p50, breaker_open, dead_letters).
- Created `backend/app/observability/__init__.py`
- Wired `backend/app/main.py` `GET /health/discovery` + `GET /metrics` (prometheus `generate_latest`) + `CorrelationIdMiddleware` outer → `StructlogContextVarsMiddleware` inner if deps present.
- Created `tests/test_queue.py` 4 tests: `test_arq_cron_hourly`, `test_retry_after_clamp` (3600→30), `test_circuit_exclude_404`, `test_dead_letter_on_999` (breaker EX60).

## Verification
```
python -c "from backend.app.worker import WorkerSettings; print(WorkerSettings.cron_jobs)" | grep -q "discover"  # pass
python -c "from backend.app.observability.metrics import discovery_jobs_total; print('metrics ok')"  # metrics ok
pytest tests/test_queue.py -q  # 4 passed
curl -s http://localhost:8000/health/discovery | jq '.sources | length >=1'  # via TestClient 200 ok
grep -q "SETNX" backend/app/discovery/circuit.py  # pass
grep -qi celery docker/docker-compose.yml → no celery (keep arq only)
```

## Files
- backend/app/worker.py (enhanced)
- backend/app/discovery/circuit.py (new)
- backend/app/observability/__init__.py (new)
- backend/app/observability/metrics.py (new)
- backend/app/main.py (wired health route)
- tests/test_queue.py (new)

## Ponytail
Reused redis, tenacity, structlog, prometheus already in deps; stdlib `email.utils.parsedate_to_datetime` for HTTP-date, no new deps, no Celery/RabbitMQ.

