# Reliability: Rate-Limit Presets and Error-Budget Guardrails

This guide covers the opinionated protection defaults introduced by
`core/common/rate_limit_presets.py` and explains how to tune them for
**pilot** (staging) and **production** deployments.

---

## Rate-limit presets

FusionAL ships three named profiles. Activate one by setting the
`RATE_LIMIT_PROFILE` environment variable (default: `pilot`).

| Profile | Requests / window | Window | Intended environment |
|---|---|---|---|
| `permissive` | 120 | 60 s | Local development |
| `pilot` | 60 | 60 s | Staging / controlled rollout *(default)* |
| `production` | 30 | 60 s | Full production |

### Activating a preset

```bash
# docker-compose / .env
RATE_LIMIT_PROFILE=production
```

```yaml
# compose.yaml
environment:
  RATE_LIMIT_PROFILE: production
```

### Overriding individual limits

Explicit per-variable overrides take precedence over the preset.
Both variables must be set together.

```bash
RATE_LIMIT_REQUESTS=100        # override request count
RATE_LIMIT_WINDOW_SECONDS=30   # override window
```

If only one of the two is set the override is ignored and the preset is used.

### Preset fallback behaviour

If `RATE_LIMIT_PROFILE` contains an unrecognised value the service logs a
`WARNING` and falls back to `pilot`:

```
WARNING fusional.reliability rate_limit.unknown_profile profile=staging available=['permissive', 'pilot', 'production'] falling_back_to=pilot
```

---

## Error-budget guardrails

The `ErrorBudgetTracker` maintains a rolling time-window of request outcomes
and emits structured log signals when the observed error rate breaches
configured thresholds.

### Default thresholds

| Signal | Default | Meaning |
|---|---|---|
| `WARNING` — `error_budget.warn` | 5 % | Error rate is elevated — investigate |
| `ERROR` — `error_budget.exceeded` | 10 % | Error budget burning fast — act now |
| Window | 300 s (5 min) | Rolling observation period |

### Log format

```
WARNING fusional.reliability error_budget.warn rate=0.0600 threshold=0.0500 errors=3 total=50 window_seconds=300
ERROR   fusional.reliability error_budget.exceeded rate=0.1200 threshold=0.1000 errors=6 total=50 window_seconds=300
```

Each log entry contains the exact rate and counts — copy-pasteable into
runbooks or incident documents.

### Configuration

```bash
ERROR_BUDGET_WARN_THRESHOLD=0.05   # default
ERROR_BUDGET_ERROR_THRESHOLD=0.10  # default
ERROR_BUDGET_WINDOW_SECONDS=300    # default (5 min)
```

### Enabling in your FastAPI app

> **Import path** — `rate_limit_presets` lives in `core/common/` which is
> added to `sys.path` at startup (see `core/main.py`).  Use the bare module
> name shown below from within the application, or `core.common.rate_limit_presets`
> if importing from outside that directory.

```python
from rate_limit_presets import configure_error_budget_tracking, ErrorBudgetConfig

app = FastAPI()

# Uses ErrorBudgetConfig.from_env() by default
tracker = configure_error_budget_tracking(app)

# Or pass a custom config:
cfg = ErrorBudgetConfig(warn_threshold=0.03, error_threshold=0.07, window_seconds=120)
tracker = configure_error_budget_tracking(app, config=cfg)
```

The tracker is also accessible at runtime via `app.state.error_budget_tracker`
for inspection or reset in integration tests.

---

## Recommended defaults by deployment mode

### Local development (`permissive`)

```bash
RATE_LIMIT_PROFILE=permissive
# No error-budget middleware needed for dev; omit configure_error_budget_tracking()
```

Goals: low friction, fast iteration.

### Pilot / staging (`pilot`)

```bash
RATE_LIMIT_PROFILE=pilot          # 60 req/60 s
ERROR_BUDGET_WARN_THRESHOLD=0.05
ERROR_BUDGET_ERROR_THRESHOLD=0.10
ERROR_BUDGET_WINDOW_SECONDS=300
```

Goals: catch regressions before production, allow enough traffic for
realistic load tests.

### Production (`production`)

```bash
RATE_LIMIT_PROFILE=production     # 30 req/60 s
ERROR_BUDGET_WARN_THRESHOLD=0.02  # tighter — alert earlier
ERROR_BUDGET_ERROR_THRESHOLD=0.05
ERROR_BUDGET_WINDOW_SECONDS=300
# Add REDIS_URL for cross-instance rate-limit consistency
REDIS_URL=redis://redis:6379/0
```

Goals: protect downstream APIs, enforce SLO burn-rate guards, cross-instance
consistency via Redis.

---

## Tuning guidance

### Rate limits

1. **Baseline** — start with the preset for your environment.
2. **Measure** — observe `429` rates in production logs for one week.
3. **Adjust** — if `429` rate is above 1 %, increase `RATE_LIMIT_REQUESTS`;
   if downstream APIs are showing strain, decrease it.
4. **Redis** — set `REDIS_URL` in production so limits are shared across all
   replicas; without it each replica tracks independently.

### Error budget

1. **Start wide** — `warn=0.05 / error=0.10` gives room for transient blips.
2. **Tighten after stabilisation** — once p99 error rate is below 1 % for
   two weeks, move to `warn=0.02 / error=0.05`.
3. **Window size** — a 5-minute window (300 s) balances responsiveness with
   noise. For batch-heavy workloads consider 600–900 s.
4. **Alert routing** — pipe `fusional.reliability` log records to your
   alerting pipeline (PagerDuty, Slack webhook, etc.).  Third-party
   integrations are out of scope for this module; forward logs at the
   infrastructure layer.

---

## Out of scope

Third-party alerting integrations (PagerDuty, OpsGenie, Slack, etc.) are
intentionally not included.  Forward `fusional.reliability` log output to
your existing log aggregation pipeline and configure alerts there.
