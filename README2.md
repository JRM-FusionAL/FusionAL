FusionAL 🔥  
**AI-Powered MCP Server Factory – Prompt → Secure Dockerized MCP Server in Minutes**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Stars](https://img.shields.io/github/stars/TangMan69/FusionAL?style=social)](https://github.com/TangMan69/FusionAL)

FusionAL lets you **generate full MCP servers from natural language**, build them safely in Docker sandboxes (no network, memory limits, non-root), register them in a catalog, and plug straight into Claude Desktop, Cursor, or any MCP client.

MCP is exploding—don't hand-craft tools anymore. Let AI do it while you stay secure.

## ✨ Features
- 🤖 AI code gen: Claude/OpenAI turns prompts into complete MCP servers (code + Dockerfile)
- 🛡️ Hardened Docker execution: isolated, no internet, dropped caps, mem/CPU limits
- 📦 Unified registry & catalog: discover, run, manage multiple servers
- ⚡ FastAPI backend + gateway for seamless MCP integration
- 🔌 Ready examples: dice roller, weather API, file utils (expandable to anything)
- 🚀 One-command spin-up with Docker Compose

## 🚀 Quick Start (Under 5 Minutes)

**Prerequisites**
- Docker Desktop (running)
- Python 3.11+
- Claude Desktop (or MCP-compatible client)

```bash
# Clone & setup
git clone https://github.com/TangMan69/FusionAL.git
cd FusionAL

# Virtual env & deps (for local dev/gateway)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r core/requirements.txt

# Start the FusionAL gateway & registry
cd core
python -m uvicorn main:app --reload --port 8009
In another terminal, build & run an example:
Bashcd ../examples/weather-api
docker build -t weather-mcp .
docker run --rm -p 8001:8000 weather-mcp

Add to Claude config (Windows example):
JSON{
  "mcpServers": {
    "fusion-weather": {
      "command": "docker",
      "args": ["run", "--rm", "-p", "8001:8000", "weather-mcp"]
    }
  }
}
Restart Claude → ask it about weather. Boom.
Full setup → see docs/SETUP.md or quick-start/ folder.

🏗️ How It Works (High-Level)
textYour Prompt → AI (Claude/OpenAI) → Generates: Python MCP code + Dockerfile + manifest
          ↓
FusionAL Builder → Validates & Builds Docker image
          ↓
Secure Sandbox Run → Registers in Catalog (YAML/JSON)
          ↓
MCP Client (Claude/Cursor) → Calls gateway → Executes tool
Security first: containers drop ALL capabilities, no net, seccomp, read-only where possible.

📈 Roadmap

Web UI for prompt → generate flow
One-click deploy to cloud (Render/Fly.io)
More examples (Stripe, Slack, local files, custom APIs)
Auto-update catalog from community

🤝 Contributing
Issues, PRs, ideas welcome. Fork → branch → PR.
DM me @2EfinAwesome on X if you build something cool with it.

📜 License
MIT – go wild, but credit if you fork heavy.
Star if you're building with MCP. Let's make agents unstoppable. 🚀