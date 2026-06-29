#!/bin/bash

# Maintenance script for FusionAL repository
# This script checks for outdated dependencies, opens a PR to update them,
# waits for CI to pass, merges the PR, labels new issues, and posts a summary.

set -euo pipefail

# Configuration
REPO_DIR="/home/jrm_fusional/Projects/FusionAL"
DRY_RUN=${DRY_RUN:-0}  # Set to 1 for dry run (no actual changes)
LOG_FILE="$REPO_DIR/.hermes/maintenance.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Logging function
log() {
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE"
}

# Ensure we are in the repo directory
cd "$REPO_DIR"

# Set up virtual environment if not present
VENV_DIR=""
for d in venv .venv env; do
    if [ -d "$REPO_DIR/$d" ]; then
        VENV_DIR="$REPO_DIR/$d"
        break
    fi
done
if [ -z "$VENV_DIR" ]; then
    VENV_DIR="$REPO_DIR/venv"
    log "Creating virtual environment at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi
log "Activating virtual environment at $VENV_DIR"
source "$VENV_DIR/bin/activate"

# Check if gh is installed and authenticated
if ! command -v gh &> /dev/null; then
    log "Error: gh CLI not found. Please install GitHub CLI."
    exit 1
fi

# Check if we are in a git repository
if ! git rev-parse --is-inside-work-tree &> /dev/null; then
    log "Error: Not a git repository."
    exit 1
fi

# Get repository full name for API calls (works for both SSH and HTTPS remotes)
REPO_FULLNAME=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || git remote get-url origin | sed -e 's|https://github.com/||;s|git@github.com:||;s|\.git$||')
log "Repository: $REPO_FULLNAME"

# Fetch latest from default branch
DEFAULT_BRANCH=$(git remote show origin | awk '/HEAD branch/ {print $NF}')
log "Fetching latest from $DEFAULT_BRANCH"
git fetch origin "$DEFAULT_BRANCH"

# Check for outdated dependencies using PyPI JSON API (no venv/internet installs needed)
log "Checking for outdated dependencies via PyPI API..."
OUTDATED_JSON=$(python3 -c "
import json, re, ssl, urllib.request, sys
pkgs = {}
for req_file in ['requirements.txt', 'core/requirements.txt']:
    try:
        with open(req_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or line.startswith('-'):
                    continue
                m = re.match(r'^([a-zA-Z0-9_.\-\[\]]+)([><=!]+)(.+)$', line)
                if m:
                    name = m.group(1).lower().split('[')[0]
                    version = m.group(3).strip()
                    if name not in pkgs:
                        pkgs[name] = version
    except FileNotFoundError:
        pass

ctx = ssl.create_default_context()
outdated = []
for name, ver in sorted(pkgs.items()):
    try:
        url = f'https://pypi.org/pypi/{name}/json'
        req = urllib.request.Request(url, headers={'User-Agent': 'fusional-maint/1.0'})
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        latest = json.loads(resp.read())['info']['version']
        cv = tuple(int(x) for x in re.findall(r'\d+', ver))
        lv = tuple(int(x) for x in re.findall(r'\d+', latest))
        if cv < lv:
            outdated.append({'name': name, 'current': ver, 'latest': latest})
    except:
        pass

print(json.dumps(outdated))
" 2>/dev/null || echo "[]")

OUTDATED_COUNT=$(echo "$OUTDATED_JSON" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)

if [ "$OUTDATED_COUNT" -eq 0 ]; then
    log "No outdated dependencies found."
    UPDATES_AVAILABLE=0
else
    log "Outdated dependencies found: $OUTDATED_COUNT packages."
    UPDATES_AVAILABLE=1
fi

# If there are updates, proceed with PR
if [ "$UPDATES_AVAILABLE" -eq 1 ]; then
    # Create a branch
    BRANCH_NAME="dependency-update-$(date '+%Y%m%d%H%M%S')"
    log "Creating branch: $BRANCH_NAME"
    git checkout -b "$BRANCH_NAME"

    # Update dependencies
    log "Updating dependencies..."
    # Extract package names from the outdated JSON and update each
    PKGS_TO_UPDATE=$(python3 -c "
import json, sys
data = json.load(sys.stdin)
for item in data:
    print(item['name'])
" <<< "$OUTDATED_JSON")
    if [ -n "$PKGS_TO_UPDATE" ]; then
        echo "$PKGS_TO_UPDATE" | xargs -n1 pip install -U
    fi

    # Update requirements.txt
    log "Updating requirements.txt"
    pip freeze > requirements.txt

    # Commit changes
    git add requirements.txt
    git commit -m "chore: update dependencies"

    # Push branch
    if [ "$DRY_RUN" -eq 1 ]; then
        log "[DRY RUN] Would push branch $BRANCH_NAME to origin"
    else
        log "Pushing branch $BRANCH_NAME to origin"
        git push -u origin "$BRANCH_NAME"
    fi

    # Open a PR
    PR_NUMBER=""
    if [ "$DRY_RUN" -eq 1 ]; then
        log "[DRY RUN] Would open a PR for branch $BRANCH_NAME"
    else
        log "Opening PR for branch $BRANCH_NAME"
        PR_OUTPUT=$(gh pr create --title "chore: update dependencies" --body "This PR updates dependencies to their latest versions." --base "$DEFAULT_BRANCH" --head "$BRANCH_NAME" 2>&1)
        log "PR output: $PR_OUTPUT"
        # Extract PR number from the output (assuming the output is the URL)
        PR_NUMBER=$(echo "$PR_OUTPUT" | grep -oE '[0-9]+$' || echo "")
        if [ -z "$PR_NUMBER" ]; then
            # Maybe the output is the URL, try to extract the number from the URL
            PR_NUMBER=$(echo "$PR_OUTPUT" | grep -oE '[0-9]+$' || echo "")
        fi
        log "PR number: $PR_NUMBER"
    fi

    # Wait for CI to pass
    # We'll poll the gh API for check runs on the PR
    # We'll wait up to 30 minutes (30 checks at 60 seconds each)
    MAX_WAIT=30
    WAIT_TIME=0
    if [ "$DRY_RUN" -eq 0 ] && [ -n "${PR_NUMBER:-}" ]; then
        log "Waiting for CI to pass on PR #$PR_NUMBER..."
        # Get the HEAD commit SHA for the PR (correct API endpoint requires commit SHA, not PR number)
        PR_HEAD_SHA=$(gh pr view "$PR_NUMBER" --repo "$REPO_FULLNAME" --json headRefOid --jq '.headRefOid' 2>/dev/null || echo "")
        if [ -z "$PR_HEAD_SHA" ]; then
            log "WARNING: Could not get PR HEAD SHA. Skipping CI wait."
        else
            log "PR HEAD commit: $PR_HEAD_SHA"
        fi
        while [ $WAIT_TIME -lt $MAX_WAIT ] && [ -n "$PR_HEAD_SHA" ]; do
            # Get check runs for the PR HEAD commit (correct endpoint)
            CHECK_RUNS=$(gh api "/repos/$REPO_FULLNAME/commits/$PR_HEAD_SHA/check-runs" --jq '.check_runs' 2>/dev/null || echo "{}")
            TOTAL_CHECKS=$(echo "$CHECK_RUNS" | python3.12 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('check_runs',[])))" 2>/dev/null || echo "0")
            COMPLETED_CHECKS=$(echo "$CHECK_RUNS" | python3.12 -c "import sys,json; d=json.load(sys.stdin); print(len([c for c in d.get('check_runs',[]) if c.get('status')=='completed']))" 2>/dev/null || echo "0")
            FAILED_CHECKS=$(echo "$CHECK_RUNS" | python3.12 -c "import sys,json; d=json.load(sys.stdin); print(len([c for c in d.get('check_runs',[]) if c.get('status')=='completed' and c.get('conclusion') in ['failure','cancelled','timed_out','action_required']]))" 2>/dev/null || echo "0")
            log "CI status: $COMPLETED_CHECKS/$TOTAL_CHECKS completed, $FAILED_CHECKS failed"
            if [ "$TOTAL_CHECKS" -gt 0 ] && [ "$COMPLETED_CHECKS" -eq "$TOTAL_CHECKS" ] && [ "$FAILED_CHECKS" -eq 0 ]; then
                log "All checks passed and completed."
                break
            fi
            sleep 60
            WAIT_TIME=$((WAIT_TIME+1))
            log "Still waiting for CI... ($WAIT_TIME/$MAX_WAIT)"
        done
        if [ $WAIT_TIME -eq $MAX_WAIT ]; then
            log "Timeout waiting for CI. Aborting."
            exit 1
        fi
    fi

    # Merge the PR if CI passes
    if [ "$DRY_RUN" -eq 1 ]; then
        log "[DRY RUN] Would merge PR #$PR_NUMBER"
    else
        if [ -n "${PR_NUMBER:-}" ]; then
            log "Merging PR #$PR_NUMBER"
            gh pr merge "$PR_NUMBER" --squash --delete-branch || log "Failed to merge PR #$PR_NUMBER"
        else
            log "PR number not found, skipping merge."
        fi
    fi

    # Label new issues
    if [ "$DRY_RUN" -eq 1 ]; then
        log "[DRY RUN] Would label new issues"
    else
        log "Labeling new issues..."
        # List open issues without labels
        ISSUES_WITHOUT_LABELS=$(gh issue list --state open --limit 50 --json number,labels --jq '.[] | select(.labels | length == 0) | .number' 2>/dev/null || echo "")
        if [ -n "$ISSUES_WITHOUT_LABELS" ]; then
            for ISSUE_NUM in $ISSUES_WITHOUT_LABELS; do
                log "Labeling issue #$ISSUE_NUM with 'triage'"
                gh issue edit "$ISSUE_NUM" --add-label "triage"
            done
        else
            log "No new issues without labels found."
        fi
    fi

    # Post a weekly summary
    if [ "$DRY_RUN" -eq 1 ]; then
        log "[DRY RUN] Would post weekly summary"
    else
        log "Posting weekly summary..."
        # We'll append to a file in the repo, e.g., MAINTENANCE.md
        SUMMARY_FILE="$REPO_DIR/MAINTENANCE.md"
        echo -e "\n## Maintenance Run: $TIMESTAMP" >> "$SUMMARY_FILE"
        echo "Outdated dependencies found: $OUTDATED_JSON" >> "$SUMMARY_FILE"
        if [ "$UPDATES_AVAILABLE" -eq 1 ]; then
            echo "Updated dependencies and opened PR #$PR_NUMBER." >> "$SUMMARY_FILE"
            echo "PR merged after CI passed." >> "$SUMMARY_FILE"
        else
            echo "No updates were needed." >> "$SUMMARY_FILE"
        fi
        echo "Labeled new issues with 'triage'." >> "$SUMMARY_FILE"
        echo "---" >> "$SUMMARY_FILE"
    fi
else
    # No updates, but we still want to label new issues and post a summary?
    # The task says: "Labels new issues (if any) with appropriate labels" and "Posts a weekly summary comment"
    # So we should do these steps even if there are no updates.
    if [ "$DRY_RUN" -eq 1 ]; then
        log "[DRY RUN] Would label new issues and post weekly summary (no updates)"
    else
        log "Labeling new issues (no updates)..."
        # Label new issues
        ISSUES_WITHOUT_LABELS=$(gh issue list --state open --limit 50 --json number,labels --jq '.[] | select(.labels | length == 0) | .number' 2>/dev/null || echo "")
        if [ -n "$ISSUES_WITHOUT_LABELS" ]; then
            for ISSUE_NUM in $ISSUES_WITHOUT_LABELS; do
                log "Labeling issue #$ISSUE_NUM with 'triage'"
                gh issue edit "$ISSUE_NUM" --add-label "triage"
            done
        else
            log "No new issues without labels found."
        fi

        # Post a weekly summary (no updates)
        log "Posting weekly summary (no updates)..."
        SUMMARY_FILE="$REPO_DIR/MAINTENANCE.md"
        echo -e "\n## Maintenance Run: $TIMESTAMP" >> "$SUMMARY_FILE"
        echo "No outdated dependencies found." >> "$SUMMARY_FILE"
        echo "Labeled new issues with 'triage'." >> "$SUMMARY_FILE"
        echo "---" >> "$SUMMARY_FILE"
    fi
fi

log "Maintenance script completed."
exit 0