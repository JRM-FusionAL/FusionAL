"""
FusionAL Command Center — Notion Poller v1
Polls Notion databases and orchestrates MCP server builds via FusionAL Engine.

Flow:
  1. Recover any "Building" rows interrupted by a previous crash
  2. Loop every POLL_INTERVAL seconds:
     a. poll_build_queue()  — Pending → Building → Complete/Failed
     b. health_check_fleet() — Running servers, incident creation/resolution
"""

import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from notion_client import Client as NotionClient
from notion_client.errors import APIResponseError
from rich.console import Console
from rich.rule import Rule

# ── Load config ─────────────────────────────────────────────────────────────
load_dotenv()

NOTION_TOKEN: str = os.getenv("NOTION_TOKEN", "")
FUSIONAL_URL: str = os.getenv("FUSIONAL_URL", "http://localhost:8009").rstrip("/")
POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "30"))
FAILURE_THRESHOLD: int = int(os.getenv("HEALTH_CHECK_FAILURES_THRESHOLD", "3"))

REGISTRY_ID = "6f4b3398-575f-439c-9f71-87bebaf91ed6"
BUILD_QUEUE_ID = "54b1b6b3-bf38-4268-94c9-a0789c0c27c0"
INCIDENT_LOG_ID = "7b0194c1-c3d6-4aa0-b45f-6b7f0e3ba371"

RICH_TEXT_LIMIT = 2000  # Notion hard limit per rich_text block

console = Console()

# ── In-memory state ──────────────────────────────────────────────────────────
# Maps Registry page_id -> consecutive health-check failure count
failure_counts: dict[str, int] = {}


# ── Utilities ────────────────────────────────────────────────────────────────

def now_iso() -> str:
    """Current UTC time as ISO 8601 string for Notion date fields."""
    return datetime.now(timezone.utc).isoformat()


def truncate_rich_text(text: str) -> str:
    """Truncate to Notion's 2000-char rich_text block limit."""
    if len(text) <= RICH_TEXT_LIMIT:
        return text
    return text[: RICH_TEXT_LIMIT - 15] + "... [truncated]"


def get_title_text(page: dict) -> str:
    """Extract plain text from the title property of a Notion page."""
    try:
        for prop in page["properties"].values():
            if prop.get("type") == "title":
                return "".join(t.get("plain_text", "") for t in prop["title"])
    except (KeyError, TypeError):
        pass
    return ""


def get_select_value(page: dict, prop_name: str) -> str:
    """Get the name of a select property value."""
    try:
        sel = page["properties"][prop_name]["select"]
        return sel["name"] if sel else ""
    except (KeyError, TypeError):
        pass
    return ""


def get_number_value(page: dict, prop_name: str) -> Optional[int]:
    """Get a numeric property value."""
    try:
        val = page["properties"][prop_name]["number"]
        return int(val) if val is not None else None
    except (KeyError, TypeError):
        pass
    return None


# ── Notion retry wrapper ─────────────────────────────────────────────────────

def notion_call(fn, *args, max_retries: int = 3, **kwargs):
    """
    Call a notion-client method with exponential backoff on HTTP 429.
    Re-raises on any other error or after exhausting retries.
    """
    delay = 2
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except APIResponseError as exc:
            if exc.status == 429 and attempt < max_retries - 1:
                console.print(
                    f"[yellow][NOTION] Rate limited — backing off {delay}s "
                    f"(attempt {attempt + 1}/{max_retries})[/yellow]"
                )
                time.sleep(delay)
                delay *= 2
            else:
                raise


# ── Build Pipeline ───────────────────────────────────────────────────────────

def poll_build_queue(notion: NotionClient, http: httpx.Client) -> None:
    """Find all Pending builds and process each one."""
    console.print("[bold cyan][POLL][/bold cyan] Querying Build Queue for Pending rows...")

    try:
        result = notion_call(
            notion.databases.query,
            database_id=BUILD_QUEUE_ID,
            filter={"property": "Status", "select": {"equals": "Pending"}},
        )
    except Exception as exc:
        console.print(f"[red][POLL] Could not query Build Queue: {exc}[/red]")
        return

    pages = result.get("results", [])
    if not pages:
        console.print("[dim][POLL] No pending builds.[/dim]")
        return

    console.print(f"[cyan][POLL] {len(pages)} pending build(s) found.[/cyan]")
    for page in pages:
        _process_build(notion, http, page)


def _process_build(notion: NotionClient, http: httpx.Client, page: dict) -> None:
    page_id = page["id"]
    prompt = get_title_text(page)

    console.print(f"[bold blue][BUILD][/bold blue] Starting: [italic]{prompt or '(empty request)'}[/italic]")

    # Mark as Building
    try:
        notion_call(
            notion.pages.update,
            page_id=page_id,
            properties={"Status": {"select": {"name": "Building"}}},
        )
    except Exception as exc:
        console.print(f"[red][BUILD] Cannot set Building status: {exc}[/red]")
        return

    # Call FusionAL /generate
    try:
        resp = http.post(
            f"{FUSIONAL_URL}/generate",
            json={"prompt": prompt, "sandbox": True},
            timeout=120.0,
        )
        resp.raise_for_status()
        data: dict = resp.json()
    except httpx.ConnectError:
        _fail_build(notion, page_id, "FusionAL unreachable — is the engine running?")
        return
    except httpx.TimeoutException:
        _fail_build(notion, page_id, "FusionAL /generate timed out after 120 s")
        return
    except httpx.HTTPStatusError as exc:
        _fail_build(notion, page_id, f"FusionAL returned HTTP {exc.response.status_code}")
        return
    except Exception as exc:
        _fail_build(notion, page_id, f"Unexpected error calling FusionAL: {exc}")
        return

    if data.get("status") == "success":
        server_name: str = data.get("server_name", "unknown-server")
        port: int = data.get("port", 0)
        tools: list = data.get("tools", [])
        logs: str = data.get("logs", "")

        description = f"Tools: {', '.join(tools)}" if tools else "No tools listed"
        output_text = truncate_rich_text(logs or "Build completed successfully.")

        # Update Build Queue → Complete
        try:
            notion_call(
                notion.pages.update,
                page_id=page_id,
                properties={
                    "Status": {"select": {"name": "Complete"}},
                    "Output": {"rich_text": [{"text": {"content": output_text}}]},
                },
            )
        except Exception as exc:
            console.print(f"[yellow][BUILD] Warning — could not write output to Build Queue: {exc}[/yellow]")

        # Create Registry entry
        try:
            notion_call(
                notion.pages.create,
                parent={"database_id": REGISTRY_ID},
                properties={
                    "Name": {"title": [{"text": {"content": server_name}}]},
                    "Status": {"select": {"name": "Running"}},
                    "Port": {"number": port},
                    "Description": {"rich_text": [{"text": {"content": description}}]},
                    "Last Updated": {"date": {"start": now_iso()}},
                },
            )
            console.print(
                f"[bold green][BUILD][/bold green] Complete: "
                f"[bold]{server_name}[/bold] on port {port} added to Registry."
            )
        except Exception as exc:
            console.print(f"[yellow][BUILD] Warning — could not create Registry entry: {exc}[/yellow]")
    else:
        error = data.get("error", "Unknown error returned by FusionAL")
        _fail_build(notion, page_id, error)


def _fail_build(notion: NotionClient, page_id: str, error_msg: str) -> None:
    """Set Build Queue row to Failed and write error to Output field."""
    console.print(f"[red][BUILD] Failed: {error_msg}[/red]")
    output_text = truncate_rich_text(f"ERROR: {error_msg}")
    try:
        notion_call(
            notion.pages.update,
            page_id=page_id,
            properties={
                "Status": {"select": {"name": "Failed"}},
                "Output": {"rich_text": [{"text": {"content": output_text}}]},
            },
        )
    except Exception as exc:
        console.print(f"[red][BUILD] Also could not update Failed status: {exc}[/red]")


# ── Health Check Fleet ───────────────────────────────────────────────────────

def health_check_fleet(notion: NotionClient, http: httpx.Client) -> None:
    """Check all Running and Error servers; handle incidents and recovery."""
    console.print("[bold cyan][HEALTH][/bold cyan] Checking server fleet...")

    pages: list = []

    for status_filter in ("Running", "Error"):
        try:
            result = notion_call(
                notion.databases.query,
                database_id=REGISTRY_ID,
                filter={"property": "Status", "select": {"equals": status_filter}},
            )
            pages.extend(result.get("results", []))
        except Exception as exc:
            console.print(f"[red][HEALTH] Could not query Registry ({status_filter}): {exc}[/red]")

    if not pages:
        console.print("[dim][HEALTH] No servers to check.[/dim]")
        return

    console.print(f"[cyan][HEALTH] {len(pages)} server(s) in scope.[/cyan]")
    for page in pages:
        _check_server(notion, http, page)


def _check_server(notion: NotionClient, http: httpx.Client, page: dict) -> None:
    page_id = page["id"]
    name = get_title_text(page) or "(unnamed)"
    port = get_number_value(page, "Port")
    current_status = get_select_value(page, "Status")

    if not port:
        console.print(f"[yellow][HEALTH] {name}: no port configured — skipping.[/yellow]")
        return

    # Probe the server's /health endpoint
    healthy = False
    try:
        resp = http.get(f"http://localhost:{port}/health", timeout=5.0)
        healthy = resp.status_code < 400
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
        healthy = False
    except Exception:
        healthy = False

    if healthy:
        failure_counts.pop(page_id, None)  # reset counter

        if current_status == "Error":
            # Auto-recovery path
            console.print(
                f"[bold green][HEALTH][/bold green] {name}:{port} — [green]recovered[/green]. "
                f"Updating status to Running."
            )
            try:
                notion_call(
                    notion.pages.update,
                    page_id=page_id,
                    properties={
                        "Status": {"select": {"name": "Running"}},
                        "Last Updated": {"date": {"start": now_iso()}},
                    },
                )
                _auto_resolve_incidents(notion, name)
            except Exception as exc:
                console.print(f"[yellow][HEALTH] Warning — could not update recovery: {exc}[/yellow]")
        else:
            console.print(f"[green][HEALTH][/green] {name}:{port} — healthy.")
            try:
                notion_call(
                    notion.pages.update,
                    page_id=page_id,
                    properties={"Last Updated": {"date": {"start": now_iso()}}},
                )
            except Exception as exc:
                console.print(
                    f"[dim yellow][HEALTH] Could not update Last Updated for {name}: {exc}[/dim yellow]"
                )
    else:
        count = failure_counts.get(page_id, 0) + 1
        failure_counts[page_id] = count
        console.print(
            f"[yellow][HEALTH][/yellow] {name}:{port} — unhealthy "
            f"(consecutive failures: {count}/{FAILURE_THRESHOLD})."
        )

        if count >= FAILURE_THRESHOLD:
            console.print(
                f"[bold red][INCIDENT][/bold red] {name} exceeded failure threshold — creating incident."
            )
            failure_counts[page_id] = 0  # reset so we don't spam incidents
            try:
                notion_call(
                    notion.pages.update,
                    page_id=page_id,
                    properties={"Status": {"select": {"name": "Error"}}},
                )
                error_msg = (
                    f"Health check failed {count} consecutive times "
                    f"(port {port} unreachable or returning errors)"
                )
                notion_call(
                    notion.pages.create,
                    parent={"database_id": INCIDENT_LOG_ID},
                    properties={
                        "Server": {"title": [{"text": {"content": name}}]},
                        "Status": {"select": {"name": "Open"}},
                        "Error": {"rich_text": [{"text": {"content": error_msg}}]},
                        "Date": {"date": {"start": now_iso()}},
                        "Notes": {"rich_text": [{"text": {"content": ""}}]},
                    },
                )
                console.print(f"[red][INCIDENT][/red] Incident opened for [bold]{name}[/bold].")
            except Exception as exc:
                console.print(f"[red][INCIDENT] Failed to create incident: {exc}[/red]")


def _auto_resolve_incidents(notion: NotionClient, server_name: str) -> None:
    """Find all Open incidents for server_name and mark them Resolved."""
    try:
        result = notion_call(
            notion.databases.query,
            database_id=INCIDENT_LOG_ID,
            filter={
                "and": [
                    {"property": "Status", "select": {"equals": "Open"}},
                    {"property": "Server", "title": {"equals": server_name}},
                ]
            },
        )
        incidents = result.get("results", [])
        if not incidents:
            return

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        for incident in incidents:
            notion_call(
                notion.pages.update,
                page_id=incident["id"],
                properties={
                    "Status": {"select": {"name": "Resolved"}},
                    "Notes": {
                        "rich_text": [
                            {"text": {"content": f"Auto-resolved: server recovered at {ts}"}}
                        ]
                    },
                },
            )
            console.print(
                f"[green][INCIDENT][/green] Auto-resolved open incident for [bold]{server_name}[/bold]."
            )
    except Exception as exc:
        console.print(f"[yellow][INCIDENT] Warning — could not auto-resolve incidents: {exc}[/yellow]")


# ── Idempotency: recover interrupted builds ──────────────────────────────────

def recover_interrupted_builds(notion: NotionClient) -> None:
    """
    On startup, any row stuck in "Building" was interrupted by a crash.
    Mark them Failed so they can be manually retried or requeued.
    """
    console.print("[POLL] Scanning for interrupted builds (stuck at Building)...")
    try:
        result = notion_call(
            notion.databases.query,
            database_id=BUILD_QUEUE_ID,
            filter={"property": "Status", "select": {"equals": "Building"}},
        )
        pages = result.get("results", [])
        if not pages:
            console.print("[dim][POLL] No interrupted builds found.[/dim]")
            return
        console.print(
            f"[yellow][POLL] Found {len(pages)} interrupted build(s) — marking as Failed.[/yellow]"
        )
        for page in pages:
            _fail_build(notion, page["id"], "Interrupted by poller restart — retry or review manually")
    except Exception as exc:
        console.print(f"[yellow][POLL] Warning — could not check for interrupted builds: {exc}[/yellow]")


# ── FusionAL Engine health check ─────────────────────────────────────────────

def check_fusional_health(http: httpx.Client) -> bool:
    """Ping FusionAL /health and report the result. Non-fatal."""
    console.print(f"[bold cyan][HEALTH][/bold cyan] Checking FusionAL engine at {FUSIONAL_URL}/health ...")
    try:
        resp = http.get(f"{FUSIONAL_URL}/health", timeout=5.0)
        if resp.status_code == 200:
            console.print(
                f"[bold green][HEALTH][/bold green] FusionAL — [green]online[/green] "
                f"({resp.json()})"
            )
            return True
        console.print(f"[yellow][HEALTH] FusionAL returned HTTP {resp.status_code}[/yellow]")
        return False
    except (httpx.ConnectError, httpx.TimeoutException):
        console.print(
            f"[bold yellow][HEALTH][/bold yellow] FusionAL unreachable at {FUSIONAL_URL} "
            f"— builds will fail until it comes online."
        )
        return False
    except Exception as exc:
        console.print(f"[yellow][HEALTH] FusionAL health error: {exc}[/yellow]")
        return False


# ── Startup banner ───────────────────────────────────────────────────────────

def _banner_line(content: str, width: int = 42) -> str:
    """Pad content to fixed inner width and wrap with box chars."""
    return f"║ {content.ljust(width)} ║"


def print_banner() -> None:
    inner = 42  # characters between '║ ' and ' ║'
    sep = "═" * (inner + 2)
    lines = [
        f"╔{sep}╗",
        _banner_line("FusionAL Command Center — Poller v1", inner),
        _banner_line("Notion → FusionAL → Docker → Notion", inner),
        f"╠{sep}╣",
        _banner_line(f"Registry DB : {REGISTRY_ID[:8]}...", inner),
        _banner_line(f"Build Queue : {BUILD_QUEUE_ID[:8]}...", inner),
        _banner_line(f"Incident Log: {INCIDENT_LOG_ID[:8]}...", inner),
        _banner_line(f"FusionAL    : {FUSIONAL_URL}", inner),
        _banner_line(f"Poll interval: {POLL_INTERVAL}s", inner),
        f"╚{sep}╝",
    ]
    console.print("\n[bold cyan]" + "\n".join(lines) + "[/bold cyan]\n")


# ── Main loop ────────────────────────────────────────────────────────────────

def main() -> None:
    if not NOTION_TOKEN:
        console.print(
            "[bold red]ERROR: NOTION_TOKEN is not set. "
            "Copy .env.example to .env and add your token.[/bold red]"
        )
        sys.exit(1)

    print_banner()

    notion = NotionClient(auth=NOTION_TOKEN)

    with httpx.Client() as http:
        check_fusional_health(http)
        recover_interrupted_builds(notion)

        console.print(
            f"\n[bold cyan][POLL][/bold cyan] Entering main loop "
            f"(interval: {POLL_INTERVAL}s). Press Ctrl+C to stop.\n"
        )

        cycle = 0
        while True:
            cycle += 1
            console.print(
                Rule(
                    f"[cyan]Cycle {cycle}  —  "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/cyan]"
                )
            )

            poll_build_queue(notion, http)
            health_check_fleet(notion, http)

            console.print(f"[dim][POLL] Sleeping {POLL_INTERVAL}s...[/dim]\n")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Shutting down FusionAL Poller — goodbye.[/bold yellow]")
        sys.exit(0)
