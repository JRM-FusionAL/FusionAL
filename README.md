# 🚀 FusionAL — Self-Hosted MCP Governance Gateway

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-orange)

> **Deploy governed MCP in weeks, not quarters.**  
> 🌐 [fusional.dev](https://fusional.dev) • 📧 [jonathanmelton.fusional@gmail.com](mailto:jonathanmelton.fusional@gmail.com) • 🗓️ [Book a Call](https://calendly.com/jonathanmelton004/30min)

A privacy-first, self-hosted **Model Context Protocol (MCP) governance gateway** for teams that need
auditability, policy controls, and reliable AI tool operations — without a dedicated platform
engineering department.

Built for regulated and privacy-sensitive environments (healthcare, legal, fintech SMBs) where
cloud-hosted tool orchestration is not acceptable. FusionAL serves the 80% of companies that need
governed MCP but can't operate it themselves.

**Core value:**
- **Self-hosted deployment** — Docker-first, your data never leaves your environment
- **Audit-ready operations** — tool call visibility and traceability
- **Policy enforcement** — control what tools can run and how
- **AI-powered server generation** — describe a tool in plain English, FusionAL builds it
- **6 documented Windows-specific MCP failure modes** solved and published
- **Done-for-you option** — we deploy, govern, and manage it for you

---

## ⚡ Quick Start (5 Minutes)

### Prerequisites
- Docker Desktop (installed and running)
- Claude Desktop
- Python 3.11+
- Git

### Step 1: Clone & Install

```bash
git clone https://github.com/JRM-FusionAL/FusionAL.git
cd FusionAL

python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

pip install -r core/requirements.txt
```

### Step 2: Start FusionAL

```bash
cd core
python -m uvicorn main:app --reload --port 8009
```

Verify it's running:
```bash
curl http://localhost:8009/health
```

### Step 3: Configure Claude Desktop

Find your config file:
- **Windows:** `C:\Users\YourName\AppData\Roaming\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`


> ⚠️ **Windows users:** Do NOT use `%APPDATA%` in the path — Claude Desktop won't expand it.
> Hardcode the full path. Example: `C:\Users\YourName\AppData\Roaming\Claude\claude_desktop_config.json`

Add FusionAL as an MCP server:

```json
{
  "mcpServers": {
    "fusional-gateway": {
      "url": "http://localhost:8009/sse"
    }
  }
}
```

### Step 4: Restart Claude Desktop & Test

Fully quit and reopen Claude Desktop. Open a new chat and try:

> *"Generate a Python MCP server that fetches the current weather for a given city."*

FusionAL will generate, register, and run it automatically.

---

## 🐳 Docker Deploy

Build and run the full gateway in Docker:

```bash
docker build -t fusional .
docker run -d -p 8089:8009 --name fusional fusional
```

Or with Docker Compose:

```bash
docker compose up -d
```

Gateway available at `http://localhost:8089`.

---

## 🏗️ Architecture

```
Claude Desktop / Any MCP Client
         │
         ▼  (SSE or Streamable HTTP)
  FusionAL Gateway  (:8009)
         │
   ┌─────┴──────┐
   ▼            ▼
FastAPI      MCP Transport (/mcp)
REST API     ├── execute_code
             ├── generate_and_execute
             └── generate_mcp_project
         │
         ▼
  Docker Sandbox Executor
  (network isolated, memory capped)
         │
         ▼
  MCP Server Registry (JSON)
  ├── business-intelligence-mcp  (:8101)
  ├── api-integration-hub        (:8102)
  └── content-automation-mcp     (:8103)
```

### MCP Tools (via `/mcp`)

| Tool | Description |
|------|-------------|
| `execute_code` | Run Python in an isolated subprocess sandbox |
| `generate_and_execute` | Plain English prompt → Claude writes it → runs it |
| `generate_mcp_project` | Describe an MCP server → Claude builds the full project |

### REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/execute` | POST | Execute Python (optional Docker sandbox) |
| `/register` | POST | Register an MCP server in the registry |
| `/catalog` | GET | List all registered servers |
| `/generate` | POST | Generate and launch a new server from a prompt |

---

## 🛠️ Showcase Servers

These servers ship with the [mcp-consulting-kit](https://github.com/JRM-FusionAL/mcp-consulting-kit)
and are pre-registered in the FusionAL gateway:

| Server | Port | Tools |
|--------|------|-------|
| `business-intelligence-mcp` | 8101 | Natural language → SQL (PostgreSQL, MySQL, SQLite) |
| `api-integration-hub` | 8102 | Slack, GitHub Issues, Stripe customer lookup |
| `content-automation-mcp` | 8103 | Web scraping, link extraction, table parsing, RSS feeds |

Start the full showcase stack:

```bash
cd ../mcp-consulting-kit
docker compose up -d
```

---

## 🔒 Security Model

### Docker Sandbox

Each code execution runs with:
- ✅ Network isolation (`--network none`)
- ✅ Memory limits (default 128 MB, configurable)
- ✅ Process limits (max 64 processes)
- ✅ Read-only filesystem (except `/tmp`)
- ✅ No privilege escalation
- ✅ Non-root user execution

### API Security (optional)

When `mcp-consulting-kit/showcase-servers/common/security.py` is present, the gateway enables:
- API key authentication on `/execute`, `/register`, `/generate`
- Rate limiting
- CORS configuration

---

## 🪟 Windows-Specific Fixes

FusionAL documents and solves 6 Windows MCP failure modes not covered in official docs:

1. **The 60-Second Silence** — Claude Desktop times out with zero error. Caused by Docker socket init lag.  
   [Read the fix →](https://dev.to/jonathanmeltonfusional/why-your-mcp-setup-keeps-timing-out-in-60-seconds-and-how-i-fixed-it-on-windows-367a)

2. **The BOM Trap** — Notepad/VS Code injects a byte-order mark into JSON configs, silently breaking MCP.  
   Fix: `[System.IO.File]::WriteAllText(path, content, New-Object System.Text.UTF8Encoding($false))`

3. **The Backslash Trap** — Windows path separators in `claude_desktop_config.json` break startup silently.  
   Use forward slashes or escaped double backslashes.

4. **`%USERPROFILE%` expansion** — Claude Desktop does NOT expand env vars in config paths. Hardcode them.

5. **Docker named pipe failure** — Docker's named pipe transport fails on WSL2. Use `/var/run/docker.sock`.

6. **Registry timeout at 8+ servers** — Claude Desktop hits a timeout threshold on lower-end hardware.  
   Cap your registry at 8 servers on i5/i7 7th gen and below.

---

## 🧰 Building Your Own MCP Server

### Using the AI Builder (via Claude Desktop)

After connecting FusionAL, ask Claude:

> *"Generate an MCP server that queries our PostgreSQL database using natural language."*

FusionAL generates the full project, builds it, and registers it in the gateway automatically.

### Manual Server Structure

```
my-server/
├── Dockerfile
├── requirements.txt
├── my_server.py       ← FastMCP tools go here
└── .env
```

### Key Rules

1. Use `@mcp.tool()` decorators on async functions
2. Single-line docstrings only (multi-line breaks some MCP clients)
3. Return formatted strings from all tools
4. Default parameters to `""` not `None`
5. Log to `sys.stderr`
6. Run as non-root in Docker

```python
from mcp.server.fastmcp import FastMCP
import sys

mcp = FastMCP("my-server")

@mcp.tool()
async def my_tool(query: str = "") -> str:
    """What this tool does in one line."""
    return f"✅ Result for: {query}"

if __name__ == "__main__":
    mcp.run(transport='stdio')
```

---

## 📚 Examples

| Example | Path | What it demonstrates |
|---------|------|----------------------|
| Dice Roller | `examples/dice-roller/` | D&D dice (8 tools), dice notation parsing |
| Weather API | `examples/weather-api/` | External API integration, error handling |
| File Utils | `examples/file-utils/` | Safe filesystem access, pagination |

---

## 🚀 Done-for-You Consulting

Don't want to self-manage? FusionAL offers done-for-you MCP deployments:

| Tier | Scope | Price |
|------|-------|-------|
| **Starter Install** | Single environment, core servers, Windows hardening | $2,500–$3,500 |
| **Core Install** | Full stack, custom servers, governance layer, team onboarding | $5,000–$9,000 |
| **Retainer** | Ongoing ops, incident response, new server builds | $1,500–$4,000/mo |

[Book a free 15-min MCP security audit →](https://calendly.com/jonathanmelton004/30min)

---

## 🤝 Contributing

Contributions welcome. Priority areas:
- New example servers
- Windows compatibility fixes
- Documentation improvements
- Test coverage

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

## 🙏 Credits

- [Anthropic](https://anthropic.com) — Claude AI + MCP protocol
- [FastAPI](https://fastapi.tiangolo.com) — API framework
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- [Docker](https://docker.com) — Container infrastructure

---

**Built by a self-taught developer who fixed the MCP problems nobody else documented.**  
🌐 [fusional.dev](https://fusional.dev) • ⭐ Star the repo if it saved you hours

---

## 🙌 Origin & Inspiration

FusionAL started with a NetworkChuck video.

If you haven't watched [*"you need to learn MCP RIGHT NOW!!"*](https://youtube.com/@NetworkChuck) — go watch it first. Chuck explains the fundamentals better than anyone, and his [docker-mcp-tutorial repo](https://github.com/theNetworkChuck/docker-mcp-tutorial) is the best starting point for understanding how MCP servers work with Docker.

The dice-roller example and quick-start structure in this repo are adapted from that tutorial (MIT licensed).

**Where FusionAL goes further:**

Chuck's tutorial shows you how to build MCP servers manually — edit a prompt template, paste it into Claude, implement the result yourself.

FusionAL removes the human from that loop entirely. Instead of a prompt file you copy-paste, `generate_mcp_project` is a live tool call — Claude describes what it wants built, FusionAL generates it, registers it, and runs it. No clipboard. No manual steps.

More importantly, Chuck's video covers Docker's MCP catalog — 300+ servers you can enable with a click. That's step one. FusionAL is what you need when a CTO asks:

> *"Great — but how do we audit what those tools are doing? How do we enforce policy? How do we make sure this doesn't become a security incident?"*

That's the gap FusionAL was built to fill: governance, auditability, and operational control for teams deploying MCP at scale — especially on Windows, where the catalog alone isn't enough.
