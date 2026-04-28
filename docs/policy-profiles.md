# FusionAL Policy Profiles

Policy profiles standardize security and execution behaviour across deployment modes.
The active profile is selected at startup via the `FUSIONAL_POLICY_PROFILE` environment
variable and is printed to the application log so it always appears in the audit trail.

## Selecting a Profile

```bash
FUSIONAL_POLICY_PROFILE=strict   # production hardening
FUSIONAL_POLICY_PROFILE=balanced # default — staging / production
FUSIONAL_POLICY_PROFILE=dev      # local development
```

If the variable is absent or unrecognised, the server falls back to `balanced` and logs
a warning.

---

## Profile Reference

| Setting | `strict` | `balanced` | `dev` |
|---|---|---|---|
| Max execution timeout | 10 s | 15 s | 30 s |
| Max memory per execution | 64 MB | 128 MB | 256 MB |
| Docker required | **yes** | no | no |
| Sandbox forced on `/generate` | **yes** | **yes** | no |
| Rate limit (per 60 s) | 30 req | 60 req | 120 req |
| Intended environment | Production | Staging / default | Local dev |

### `strict`

Highest security posture for production deployments.

- All `/execute` requests **must** set `use_docker: true`.  Requests without Docker are
  rejected with HTTP 400.
- Execution timeout is capped at **10 seconds** even if the caller requests more.
- Memory is capped at **64 MB**.
- `/generate` always runs in sandbox mode regardless of the `sandbox` field in the
  request body.
- Rate limiting is set to **30 requests per 60 seconds**.

### `balanced` *(default)*

Sensible defaults for staging environments and moderate-risk production deployments.

- Docker is recommended but not required; callers may set `use_docker: false`.
- Execution timeout is capped at **15 seconds**.
- Memory is capped at **128 MB**.
- `/generate` sandbox is always enforced.
- Rate limiting is set to **60 requests per 60 seconds**.

### `dev`

Permissive settings for local development and inner-loop iteration.

- Docker is optional.
- Execution timeout is capped at **30 seconds**.
- Memory is capped at **256 MB**.
- Sandbox on `/generate` is **not** enforced — callers may set `sandbox: false`.
- Rate limiting is set to **120 requests per 60 seconds**.

---

## Startup Log

On boot, the server emits a structured INFO log entry, e.g.:

```
INFO fusional.policy policy.active profile=balanced max_timeout=15s max_memory=128MB require_docker=False force_sandbox=True rate_limit=60req/60s description='Staging/production default — Docker recommended, moderate limits'
```

This line is always present and can be used to verify the active profile in CI, smoke
tests, or audit queries.

---

## Enforcement Behaviour

| Request field | Enforcement |
|---|---|
| `timeout` | Clamped to `max_timeout_seconds` if caller requests more |
| `memory_mb` | Clamped to `max_memory_mb` if caller requests more |
| `use_docker=false` | Rejected (HTTP 400) when profile is `strict` |
| `sandbox=false` on `/generate` | Silently overridden to `true` when `force_sandbox` is set |

Clamping is silent — the effective value is used without returning an error — so existing
clients continue to function across profile changes.

---

## Adding a Custom Profile

Extend `PROFILES` in `core/policy_profiles.py`:

```python
from core.policy_profiles import PROFILES, PolicyProfile

PROFILES["enterprise"] = PolicyProfile(
    name="enterprise",
    description="Custom enterprise hardening",
    max_timeout_seconds=8,
    max_memory_mb=48,
    require_docker=True,
    force_sandbox=True,
    rate_limit_requests=20,
    rate_limit_window_seconds=60,
)
```

Then set `FUSIONAL_POLICY_PROFILE=enterprise` before starting the server.
