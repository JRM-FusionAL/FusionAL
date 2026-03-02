# Security Hardening Runbook

## API key lifecycle (SEC-02)

### Environment model

- `API_KEYS`: comma-separated active keys for zero-downtime rotation (example: `new-key,old-key`)
- `API_KEY`: legacy single-key fallback when `API_KEYS` is not set
- `REVOKED_API_KEYS`: comma-separated denylist of compromised/revoked keys

### Generate / rotate / revoke

1. Generate a new key in your secret manager.
2. Set `API_KEYS` to include both new and old keys (`new,old`).
3. Deploy and verify traffic succeeds with both keys during overlap.
4. Revoke old key by adding it to `REVOKED_API_KEYS`.
5. Remove old key from `API_KEYS` after all clients have switched.

A runtime revoke helper is available in the shared module: `revoke_api_key(app, api_key)`.

## Rate limiting with Redis (SEC-01)

### Redis environment model

- `REDIS_URL`: enables shared counters and TTL windows across instances.
- `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`: unchanged request/window controls.

### Degraded behavior

If Redis is unavailable, the limiter logs a warning and falls back to in-memory buckets.
This preserves endpoint behavior and status codes (`429` when limits are exceeded), while reducing cross-instance consistency until Redis recovers.

## Structured log redaction (SEC-05)

Observability middleware masks sensitive fields before serialization, including:

- `Authorization` / token-like headers
- `X-API-Key`
- Cookie and secret/password-like fields

Masked values are logged in redacted form and never emitted raw by the structured logger.

## CI vulnerability triage and waiver (SEC-08)

CI now runs dependency and image vulnerability scans.

- Failing threshold: high and critical vulnerabilities for container scan.
- Temporary waivers: add CVE IDs to `.trivyignore` with justification in SEC-TRACKER issue #11.
- Cleanup policy: remove waivers after package/image upgrade lands.
