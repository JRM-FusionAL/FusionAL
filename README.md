# 🚀 **FusionAL** - Self-Hosted MCP Governance Gateway

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-orange)
![Stars](https://img.shields.io/github/stars/TangMan69/FusionAL?style=social)

A privacy-first, self-hosted **Model Context Protocol (MCP) governance gateway** for teams that need auditability, policy controls, and reliable operations across AI toolchains.

Built for regulated and privacy-sensitive environments (healthcare, legal, fintech SMBs) where cloud-hosted tool orchestration is not acceptable.

Core value:
- **Self-hosted deployment** (Docker-first)
- **Audit-ready operations** (tool call visibility and traceability)
- **Policy enforcement** (control what tools can run and how)
- **Privacy-first architecture** (keep sensitive data in your environment)
- **Cross-platform reliability** including hard-earned Windows operational fixes

---

## 🎯 What is FusionAL?

FusionAL provides a governance control layer for MCP operations:

1. **Centralizing** MCP server access behind a self-hosted gateway
2. **Enforcing** policies for tool availability, limits, and runtime behavior
3. **Auditing** MCP activity for compliance and incident response
4. **Deploying** governed MCP access to Claude Desktop and other MCP-compatible clients

---

## 🏢 Enterprise Positioning

FusionAL is moving from "tool bundle" positioning to an **enterprise MCP governance gateway**:

- **Community**: open-source gateway + deployment templates
- **Enterprise**: governance features (policy profiles, audit exports, tenant controls, rate-limit presets)
- **Services**: architecture, rollout, and hardening for production MCP deployments

If you need implementation support, current consulting focus is MCP governance rollout for healthcare, legal, and fintech SMBs.

---

## ⚡ Quick Start (5 Minutes)

### Prerequisites
- Docker Desktop installed and running
- Claude Desktop (or compatible MCP client)
- Python 3.11+

### Step 1: Clone & Setup

```bash
git clone https://github.com/TangMan69/FusionAL.git
cd FusionAL

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r core/requirements.txt
```

### Step 2: Start FusionAL Server

```bash
# From the core directory
cd core
python -m uvicorn main:app --reload --port 8089
```

### Step 2b: Attach FusionAL to VS Code Debugger

This repo includes ready-to-use VS Code configs in `.vscode/`.

1. Open the **Run and Debug** panel in VS Code.
2. Select **FusionAL: Attach (debugpy :5678)**.
3. Press **F5**.

VS Code will start FusionAL under `debugpy` and attach automatically.

### Step 3: Build Example (Dice Roller)

```bash
cd examples/dice-roller
docker build -t dice-mcp-server .
```

### Step 4: Configure Claude Desktop

Find your Claude config:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

Add the FusionAL gateway:

```json
{
  "mcpServers": {
    "fusional-gateway": {
      "command": "C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe",
      "args": [
        "run", "-i", "--rm",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", "[YOUR_HOME]/.docker/mcp:/mcp",
        "docker/mcp-gateway",
        "--catalog=/mcp/catalogs/docker-mcp.yaml",
        "--catalog=/mcp/catalogs/custom.yaml",
        "--config=/mcp/config.yaml",
        "--registry=/mcp/registry.yaml",
        "--transport=stdio"
      ]
    }
  }
}
```

Replace `[YOUR_HOME]` with:
- macOS: `/Users/your_username`
- Windows: `C:\\Users\\your_username`
- Linux: `/home/your_username`

### Step 5: Restart & Test

1. Quit and restart Claude Desktop
2. Open a new chat
3. Try: _"Roll 2d6+5 for damage"_

---

## 🏗️ Architecture

```
Claude Desktop / Any MCP Client
         ↓
   Docker MCP Gateway
         ↓
   FusionAL Platform
    ┌────┬────┬────┐
    ↓    ↓    ↓    ↓
 FastAPI Sandbox Registry AI Agent
  Server  (Docker) (JSON)  (Claude/OpenAI)
```

### Core Components

| Component | Purpose |
|-----------|---------|
| **main.py** | FastAPI REST server with /execute, /register, /catalog endpoints |
| **runner_docker.py** | Hardened Docker sandbox executor with security constraints |
| **ai_agent.py** | Claude/OpenAI integration for MCP server generation |

### Docker Sandbox Constraints

Each execution runs with:
- ✅ Network isolation (`--network none`)
- ✅ Memory limits (default 128MB, configurable)
- ✅ Process limits (max 64 processes)
- ✅ No privilege escalation
- ✅ All capabilities dropped
- ✅ Read-only filesystem (except /tmp)
- ✅ Non-root user execution

---

## 🛠️ Building Your First MCP Server

### Using the AI-Powered Builder

```python
from core.ai_agent import generate_mcp_project

# Generate a complete server from a description
result = generate_mcp_project(
    prompt="Build a weather MCP server that gets current weather and 5-day forecast using OpenWeather API",
    provider="claude",
    out_dir="./my-weather-server",
    build=True,
    image_tag="weather-mcp:latest"
)

print(f"Generated files: {result['files']}")
print(f"Docker image built: {result['build_result']['image_tag']}")
```

### Manual MCP Server Structure

```
my-server/
├── Dockerfile           # Docker configuration
├── requirements.txt     # Python dependencies
├── my_server.py        # Main MCP server (with @mcp.tool() decorators)
├── README.md           # Documentation
└── .env                # Secrets (not committed)
```

### Key Rules for MCP Servers

1. ✅ Use `@mcp.tool()` decorators on async functions
2. ✅ Single-line docstrings ONLY (multi-line breaks gateway)
3. ✅ Return formatted strings from all tools
4. ✅ Default parameters to empty strings `""` not `None`
5. ✅ Log to `sys.stderr`
6. ✅ Run as non-root in Docker

Example:

```python
from mcp.server.fastmcp import FastMCP
import logging
import sys

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger("myserver")
mcp = FastMCP("myserver")

@mcp.tool()
async def my_tool(param: str = "") -> str:
    """Concise single-line description of what this does."""
    try:
        # Implementation
        return "✅ Result"
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"❌ Error: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport='stdio')
```

---

## 📚 Examples

### Built-in Examples

1. **Dice Roller** (`examples/dice-roller/`) - D&D dice rolling suite (8 tools)
   - Roll standard dice, custom dice, stats, advantage/disadvantage rolls
   - Demonstrates: Dice notation parsing, utility functions

2. **Weather API** (`examples/weather-api/`) - Real-time weather information
   - Get current weather, multi-day forecasts, parse weather data
   - Demonstrates: External API integration, error handling

3. **File Utilities** (`examples/file-utils/`) - File system operations
   - Count lines, get file info, search text, list files
   - Demonstrates: Safe filesystem access, pagination, permissions handling

### Generating More Examples

Use the AI agent to generate servers for:
- Task tracking (Todoist, Toggl integration)
- Web scraping with BeautifulSoup
- Database queries (PostgreSQL, MongoDB)
- API integrations (GitHub, Slack, Stripe)
- Code analysis and linting
- Automation workflows

---

## 🔌 API Reference

### POST /execute

Execute Python code with optional Docker sandboxing.

```bash
curl -X POST http://localhost:8089/execute \
  -H "Content-Type: application/json" \
  -d '{
    "language": "python",
    "code": "print(2 + 2)",
    "timeout": 5,
    "use_docker": true,
    "memory_mb": 128
  }'
```

### POST /register

Register a new MCP server.

```bash
curl -X POST http://localhost:8089/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "dice-roller",
    "description": "D&D dice rolling",
    "url": "docker://dice-mcp-server",
    "metadata": {"version": "1.0","tools": ["roll_dice", "roll_stats"]}
  }'
```

### GET /catalog

List all registered MCP servers.

```bash
curl http://localhost:8089/catalog
```

### GET /health

Health check.

```bash
curl http://localhost:8089/health
```

---

## 🔒 Security Model

### Docker Sandbox Features

- **Network Isolation**: No external network access
- **Memory Limits**: Prevents DoS via memory exhaustion
- **Process Limits**: Caps runaway process forks
- **Filesystem**: Read-only root with tmpfs /tmp
- **User Isolation**: Runs as non-root (UID 1000)
- **Capability Drop**: All Linux capabilities dropped

### Limitations

- Designed for **developer machines**, not production hardening
- For production, add: AppArmor/SELinux, privilege gating, resource monitoring
- External API calls not possible (network isolation)

---

## 🚀 Deployment

### Local Development

```bash
cd core
python -m uvicorn main:app --reload --port 8089
```

### Production (Docker)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY core/ .
RUN pip install -r requirements.txt
EXPOSE 8089
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8089"]
```

Build and run:

```bash
docker build -t fusional-server .
docker run -p 8089:8089 -v /var/run/docker.sock:/var/run/docker.sock fusional-server
```

---

## 📖 Documentation

- [Quick Start Guide](quick-start/setup-guide.md)
- [Building Custom Servers](docs/custom-servers.md)
- [Docker MCP Gateway Architecture](docs/docker-gateway.md)
- [Troubleshooting](docs/troubleshooting.md)

---

## 🤝 Contributing

Contributions welcome! Areas to help:

- Build new example servers
- Improve documentation
- Add tests
- Optimize Docker constraints
- Multi-language support

---

## 📄 License

MIT License - see [LICENSE](LICENSE)

---

## 🙏 Credits

- **MCP Foundation** - Model Context Protocol
- **Anthropic** - Claude AI
- **Docker** - Container technology
- **FastAPI** - API framework

---

## ☕ Support

- 🐛 Found a bug? [Open an issue](https://github.com/TangMan69/FusionAL/issues)
- 💡 Have an idea? Submit a discussion
- ⭐ Like it? Star the repo!

---

**Let's build the future of AI-powered automation tools together! 🚀**
