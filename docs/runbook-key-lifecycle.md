# Key Lifecycle Runbook — FusionAL Gateway

**Audience:** FusionAL operators and client admins  
**Scope:** API key issuance, rotation, and emergency revocation  
**Out of scope:** External KMS integration (future)

---

## Architecture Notes

- Raw keys are **never stored**. FusionAL persists only the SHA-256 hash.
- Keys are **tenant-scoped** — a key issued for `acme-corp` will be rejected on any other tenant's requests.
- Revocation is **synchronous** — the next inbound request after `revoke_key()` is called will return `403`.
- All revocation events are appended to `/data/fusional/audit.log`.

---

## Key Format

```
fal_<40 hex characters>
```

Example: `fal_3a9f21c04d87e561b294af03d12c8749a0fe6b3d1`

---

## 1. Issue a Key

**Via admin API:**
```bash
curl -X POST https://gateway.fusional.dev/admin/keys \
  -H "X-Admin-Token: <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "acme-corp", "label": "acme-prod-key-1"}'
```

**Response:**
```json
{
  "raw_key": "fal_3a9f21c04d87e561b294af03d12c8749a0fe6b3d1",
  "tenant_id": "acme-corp",
  "label": "acme-prod-key-1",
  "created_at": "2026-03-02T14:00:00Z"
}
```

> ⚠️ **The raw key is returned exactly once.** Deliver it to the client over a secure channel (encrypted email, 1Password share, etc.). It cannot be retrieved again — only revoked and re-issued.

**Via Python (direct):**
```python
from services.key_manager import issue_key
raw_key = issue_key(tenant_id="acme-corp", label="acme-prod-key-1")
# Deliver raw_key to client — do not log it
```

---

## 2. Client Usage

Clients include two headers on every request:

```
X-API-Key: fal_3a9f21c04d87e561b294af03d12c8749a0fe6b3d1
X-Tenant-ID: acme-corp
```

Any request missing either header → `401 Unauthorized`  
Any request with a revoked or mismatched key → `403 Forbidden`

---

## 3. Rotate a Key

Use this when a key may have been exposed or as part of scheduled rotation.

**Step 1 — Issue new key**
```bash
curl -X POST https://gateway.fusional.dev/admin/keys \
  -H "X-Admin-Token: <admin_token>" \
  -d '{"tenant_id": "acme-corp", "label": "acme-prod-key-2"}'
```

**Step 2 — Deliver new key to client and confirm switchover**

Both keys are valid during the transition window. Do not revoke the old key until the client confirms the new key is working.

**Step 3 — Revoke old key**
```bash
curl -X POST https://gateway.fusional.dev/admin/keys/revoke \
  -H "X-Admin-Token: <admin_token>" \
  -d '{"raw_key": "fal_<old_key>", "revoked_by": "operator-jrm"}'
```

---

## 4. Emergency Revocation

Use when a key is confirmed compromised. **Revocation is immediate.**

```bash
curl -X POST https://gateway.fusional.dev/admin/keys/revoke \
  -H "X-Admin-Token: <admin_token>" \
  -d '{"raw_key": "fal_<compromised_key>", "revoked_by": "emergency"}'
```

**Via Python (direct, fastest path):**
```python
from services.key_manager import revoke_key
revoke_key(raw_key="fal_<compromised_key>", revoked_by="emergency")
```

After revocation:
- The key is blocked on the next inbound request (no restart required)
- The event is written to `/data/fusional/audit.log`
- Issue a replacement key immediately if the client is legitimate

---

## 5. Verify Revocation

**Check audit log:**
```bash
grep "KEY_REVOKED\|REVOKED_KEY_ATTEMPT" /data/fusional/audit.log | tail -20
```

**Sample output:**
```
2026-03-02T14:05:00Z KEY_REVOKED tenant=acme-corp hash=3a9f21c04d87... actor=emergency
2026-03-02T14:05:02Z REVOKED_KEY_ATTEMPT tenant=acme-corp hash=3a9f21c04d87...
```

The `REVOKED_KEY_ATTEMPT` line confirms the revoked key was used and blocked.

---

## 6. List All Keys for a Tenant

```python
from services.key_manager import list_keys
keys = list_keys("acme-corp")
for k in keys:
    print(k.label, "REVOKED" if k.is_revoked else "ACTIVE")
```

---

## 7. Audit Log Location

| File | Purpose |
|------|---------|
| `/data/fusional/keys.db` | Key metadata (SQLite) |
| `/data/fusional/audit.log` | Append-only revocation event log |

Both files are included in standard FusionAL backup procedures.

---

## Error Reference

| HTTP Code | Meaning |
|-----------|---------|
| `401` | Missing `X-API-Key` or `X-Tenant-ID` header |
| `403` | Key not found, revoked, or tenant mismatch |

---

*Last updated: 2026-03-02 | Maintainer: JRM / FusionAL*
