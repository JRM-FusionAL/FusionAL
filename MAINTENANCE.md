## Maintenance Run: 2026-06-25 02:10:16
No outdated dependencies found via uv check.
PRs closed: #30 (mcp — already in core/reqs), #41 (stale previous run, CI failed)
PRs merged: #35 (uvicorn 0.45.0→0.48.0), #36 (anthropic 0.88.0→0.104.1), #37 (otel 1.40.0→1.42.1), #42 (mcp 1.26.0→1.27.1)
Issues labeled: none (no open unlabeled issues)
Deps updated in core/requirements.txt: uvicorn, anthropic, mcp[cli], opentelemetry-sdk/instrumentation/exporter
Pending: requests (2.33.1), pydantic (2.13.4) — not covered by Dependabot yet
---
## Maintenance Run: 2026-06-26 02:08:30
No outdated dependencies found.
Labeled new issues with 'triage'.
---
## Maintenance Run: 2026-06-27 02:06:42
No outdated dependencies found.
Labeled new issues with 'triage'.
---
## Maintenance Run: 2026-06-28 02:10:00
Deps updated: 12 packages
Commit: 6bb7cdc
---
## Maintenance Run: 2026-07-01 02:47:28
Outdated dependencies found: 6 packages (anthropic 0.111.0→0.115.0, fastapi 0.138.0→0.138.2, mcp 1.28.0→1.28.1, mypy 1.20.2→2.1.0, openai 2.43.0→2.44.0, redis 8.0.0→8.0.1)
Created branch: dependency-update-20260701024755
Updated requirements.txt and core/requirements.txt
Opened PR #45
Fixed pydantic-core version conflict (2.47.0 → 2.46.4 to match pydantic 2.13.4)
CI passed: CodeQL analysis, Automatic Dependency Submission
Merged PR #45 (squash merge, branch deleted)
Issues labeled: none (no open unlabeled issues)
---
## Maintenance Run: 2026-07-04 02:14:17
Outdated dependencies found: 7 packages (including anthropic, fastapi, filelock, pydantic-core, typing_extensions, uvicorn).
Created branch: dependency-update-20260704021443
Updated requirements.txt
Opened PR #46
CI passed: CodeQL analysis (Analyze (python) and CodeQL) and CodeRabbit
Merged PR #46 (squash merge, branch deleted)
Issues labeled: none (no open unlabeled issues)
---

## Maintenance Run: 2026-07-05 02:22:55
Outdated dependencies found: 2 packages (stevedore 5.8.0→5.9.0 and one other?)
Created branch: dependency-update-20260705021220
Updated requirements.txt
Opened PR #47
PR merged after CI passed.
Labeled new issues with 'triage' (none found).
---\n

## Maintenance Run: 2026-08-17 02:25:47
Outdated dependencies found: 2
Labeled new issues with 'triage'.
---

## Maintenance Run: 2026-08-27 02:07:02
Outdated dependencies found: 9 packages (click 8.4.2→8.5.0, nemo-relay 0.7.3→0.8.0, openai 3.3.1→3.2.0, websockets 17.0.1→17.1, etc.)
Created branch: dependency-update-20260827020811
Updated requirements.txt
Opened PR #104
Merged PR #104 (squash merge, branch deleted)
Issues labeled: none (no open unlabeled issues)
Maintenance summary: 2026-08-28 02:04
Dependencies: 10 outdated found (anthropic, honcho-ai, huggingface_hub, nemo-relay, openai, ruff + others). Protected: mcp==1.28.1, pydantic_core==2.46.4 preserved (SI-111 guard).
Branch: dependency-update-20260828020541 pushed. PR #105 created: https://github.com/JRM-FusionAL/FusionAL/pull/105
CI: 3 checks queued/in-progress (Analyze JS/Actions/Python). Awaiting pass before merge.
Labels: 0 open issues without labels (nothing to tag).
---
