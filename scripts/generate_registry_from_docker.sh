#!/usr/bin/env bash
# Generate core/mcp_registry.json from running Docker containers.
# Usage:
#   ./generate_registry_from_docker.sh             # include all running containers
#   ./generate_registry_from_docker.sh --label mcp=true
#   ./generate_registry_from_docker.sh --image-regex '^my-mcp-.*$'

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REGISTRY_PATH="$REPO_ROOT/core/mcp_registry.json"
BACKUP_PATH="$REGISTRY_PATH.bak"

LABEL=""
IMAGE_REGEX=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="$2"; shift 2;;
    --image-regex)
      IMAGE_REGEX="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI not found. Install Docker Desktop and ensure 'docker' is in PATH." >&2
  exit 1
fi

echo "Backing up existing registry (if present) to $BACKUP_PATH"
if [[ -f "$REGISTRY_PATH" ]]; then cp -f "$REGISTRY_PATH" "$BACKUP_PATH"; fi

if [[ -n "$LABEL" ]]; then
  echo "Listing containers with label: $LABEL"
  LINES=$(docker ps --filter "label=$LABEL" --format '{{.Names}} {{.Image}}')
elif [[ -n "$IMAGE_REGEX" ]]; then
  echo "Listing containers with image matching regex: $IMAGE_REGEX"
  ALL=$(docker ps --format '{{.Names}} {{.Image}}')
  LINES=$(echo "$ALL" | grep -Ei "$IMAGE_REGEX" || true)
else
  echo "Listing all running containers"
  LINES=$(docker ps --format '{{.Names}} {{.Image}}')
fi

if [[ -z "$LINES" ]]; then
  echo "Warning: No running containers matched the criteria." >&2
fi

# Build JSON via Python for reliability
python - <<PY
import sys, json, datetime
lines = """$LINES""".strip().splitlines()
obj = {}
# keep test-server from backup if available
try:
    with open('$BACKUP_PATH','r',encoding='utf-8') as f:
        existing = json.load(f)
        if 'test-server' in existing:
            obj['test-server'] = existing['test-server']
except Exception:
    pass

for line in lines:
    if not line.strip():
        continue
    parts = line.split()
    name = parts[0]
    image = parts[1] if len(parts) > 1 else ''
    entry = {
        'description': f'Docker container {name} (image: {image})',
        'url': f'docker://{name}',
        'metadata': {'version': 'unknown', 'tools': []},
        'registered_at': datetime.datetime.utcnow().isoformat() + 'Z'
    }
    obj[name] = entry

with open('$REGISTRY_PATH','w',encoding='utf-8') as f:
    json.dump(obj, f, indent=2)
print('Wrote registry to $REGISTRY_PATH')
PY
