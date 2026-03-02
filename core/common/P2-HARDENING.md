# P2 Security Hardening Runbook

## CORS Allowlist Hardening (SEC-04)

### Environment model

- `ALLOWED_ORIGINS`: comma-separated list of production-approved origins.
  - Wildcards (`*`) are automatically rejected with warning logs.
  - Invalid URI schemes (non-http/https) are rejected.

### Validation behavior

```bash
# Valid configuration
ALLOWED_ORIGINS=https://app.example.com,https://api.example.com

# Invalid patterns (auto-rejected):
ALLOWED_ORIGINS=https://app.example.com,*,ftp://bad.com
# Result: only https://app.example.com allowed
```

---

## Request ID Validation & Propagation (SEC-06)

### Inbound validation

- Accepts alphanumeric + dash/underscore only; max 64 characters.
- Malformed or missing IDs generate a new UUID.
- Invalid IDs logged with warning at startup.

### Response headers

All responses include `X-Request-ID` containing the validated ID.

### Downstream propagation

Pass `X-Request-ID` header when calling downstream services for trace continuity.

---

## Security Response Headers (SEC-07)

All API responses include baseline headers:

- `X-Content-Type-Options: nosniff` — prevents MIME type sniffing
- `X-Frame-Options: DENY` — prevents clickjacking
- `Referrer-Policy: strict-origin-when-cross-origin` — restricts referrer leakage
- `Content-Security-Policy: default-src 'self'; ...` — limits resource origins

No client-side code modifications needed; headers applied globally by middleware.

---

## Rate-Limit Abuse & Burst Testing (SEC-09)

Covered by new test cases:

- `test_enforce_rate_limit_blocks_burst_same_route` — verifies consecutive requests on same path are counted
- `test_enforce_rate_limit_per_route_isolation` — confirms limits are per-route, not global
- `test_enforce_rate_limit_different_paths_tracked_separately` — isolated tracking per endpoint

---

## Managed Secrets Best Practices (SEC-03)

### Production deployment checklist

- [ ] Use a managed secret service (AWS Secrets Manager, HashiCorp Vault, etc.)
- [ ] Never commit plaintext secrets to version control
- [ ] Inject secrets at runtime via environment variables or mount points
- [ ] Rotate secrets on a defined schedule (e.g., quarterly)
- [ ] Audit secret access and rotation events
- [ ] Use service-level IAM policies to restrict secret access

### Startup validation

The app fails fast if required secrets are missing:

```python
for required_key in ["API_KEY", "DB_PASSWORD"]:
    if not os.getenv(required_key):
        raise RuntimeError(f"Missing required secret: {required_key}")
```

Future: Integrate with AWS Secrets Manager or Vault in docker-compose/Kubernetes.

---

## Authentication Migration Plan (SEC-10)

### Current state (shared API key)

- Single static key shared across services
- No audit trail or revocation granularity
- Least-privilege not enforced

### Migration phases

#### Phase 1: Dual auth (3–6 months)
- Deploy JWT token generation service
- Accept both shared key and JWT tokens
- Document JWT claims for scoping (e.g., `service=bi`, `actions=read`)

#### Phase 2: JWT rollout (1–2 months)
- Require JWT for new clients
- Old key holders still supported
- Log deprecation warnings

#### Phase 3: Shared key deprecation (1 month)
- Remove shared key support
- Migrate all clients to JWT or mTLS
- Archive old key history

### Scope model (phase 1+)

```json
{
  "sub": "service-bi",
  "scopes": ["nl-query:read", "schema:read"],
  "exp": 1708200000,
  "iat": 1708113600
}
```

Services enforce scopes at endpoint level. Tokens signed by central auth server and verified via public key.

### Alternatives

- **JWT (recommended)**: simple, stateless, widely supported
- **mTLS**: higher complexity, better for service-to-service in Kubernetes
- **OAuth2**: adds identity provider overhead, good for user-facing flows

### Rollout risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Token leak | Short TTL (5 min), refresh token rotation |
| Clock skew | Allowable drift ±30 seconds, NTP sync |
| Token revocation delay | Token blacklist cache with short TTL |
| Downstream service integration | Gradual rollout per service, canary testing |

### Next steps

1. Design JWT claims and signing cert scheme
2. Implement token generation in auth service
3. Begin Phase 1 acceptance tests
4. Update deployment docs with JWT setup
