"""
FusionAL AI Agent

Generates MCP servers using Claude or OpenAI, orchestrates execution,
and manages MCP project scaffolding with Docker integration.
"""

import os
import requests
from dotenv import load_dotenv
import openai
import json
import subprocess  # nosec B404
import tempfile
import re

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8009")

# Model selection — override via env vars to swap models without code changes
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo")
HTTP_REQUEST_TIMEOUT_SECONDS = int(os.getenv("HTTP_REQUEST_TIMEOUT_SECONDS", "30"))

if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY


def generate_python_from_claude(prompt: str, model: str = None) -> str:
    """Generate Python code using Claude API."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
    model = model or ANTHROPIC_MODEL

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    body = {
        "model": model,
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    resp = requests.post(
        url,
        headers=headers,
        data=json.dumps(body),
        timeout=HTTP_REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    code = data["content"][0]["text"]
    return code


def generate_python_from_openai(prompt: str, model: str = None) -> str:
    """Generate Python code using OpenAI API."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set in environment")
    model = model or OPENAI_MODEL

    messages = [
        {
            "role": "system",
            "content": "You are an expert MCP server developer. Output complete, working code with proper error handling."
        },
        {"role": "user", "content": prompt},
    ]

    resp = openai.ChatCompletion.create(
        model=model,
        messages=messages,
        max_tokens=4096
    )
    code = resp.choices[0].message.content
    return code


def generate_and_execute(
    prompt: str,
    provider: str = "claude",
    timeout: int = 5,
    use_docker: bool = True
):
    """
    Generate Python code with AI and execute on FusionAL server.

    Args:
        prompt: Task description for code generation
        provider: "claude" or "openai"
        timeout: Execution timeout in seconds
        use_docker: Use Docker sandboxing (recommended)

    Returns:
        Dict with 'generated_code' and 'execution_result'
    """
    if provider == "claude":
        code = generate_python_from_claude(prompt)
    else:
        code = generate_python_from_openai(prompt)

    payload = {
        "language": "python",
        "code": code,
        "timeout": timeout,
        "use_docker": use_docker
    }
    # Timeout is explicitly set based on execution timeout budget.
    res = requests.post(  # nosec B113
        f"{SERVER_URL}/execute",
        json=payload,
        timeout=max(timeout + 5, 10),
    )
    res.raise_for_status()
    
    return {
        "generated_code": code,
        "execution_result": res.json()
    }


def _parse_files_from_ai_output(text: str):
    """Parse multi-file output from AI using === FILE: path === markers."""
    files = {}
    current_path = None
    buf = []
    
    for line in text.splitlines():
        m = re.match(r"^=== FILE: (.+) ===$", line.strip())
        if m:
            if current_path:
                files[current_path] = "\n".join(buf).lstrip("\n")
            current_path = m.group(1).strip()
            buf = []
        else:
            if current_path:
                buf.append(line)
    
    if current_path:
        files[current_path] = "\n".join(buf).lstrip("\n")
    
    return files


def generate_mcp_project(
    prompt: str,
    provider: str = "claude",
    out_dir: str = None,
    build: bool = False,
    image_tag: str = None
):
    """
    Generate a complete MCP server project using AI.

    Outputs multiple files delimited with: === FILE: path/to/file ===

    Args:
        prompt: Description of the MCP server to create
        provider: "claude" or "openai"
        out_dir: Output directory for generated files
        build: Automatically build Docker image
        image_tag: Docker image tag (auto-generated if not provided)

    Returns:
        Dict with 'out_dir', 'files', and optional 'build_result'
    """
    # Try to load builder prompt template
    builder_intro = (
        "You are an expert MCP server developer. Generate a complete MCP server project.\n"
        "Output files using === FILE: path/to/file === markers.\n"
        "Include: Dockerfile, requirements.txt, main_server.py, README.md\n"
        "Follow MCP best practices: single-line docstrings, proper error handling, logging to stderr.\n"
    )

    # Check for local template
    template_paths = [
        os.path.join(os.path.dirname(__file__), "..", "mcp-builder-prompt", "mcp-builder-prompt.md"),
        "mcp-builder-prompt/mcp-builder-prompt.md",
    ]
    
    for path in template_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                builder_intro = f.read()
            break

    full_prompt = (
        f"{builder_intro}\n\n"
        f"User request:\n{prompt}\n\n"
        "Output all files using: === FILE: relative/path ==="
    )

    if provider == "claude":
        ai_output = generate_python_from_claude(full_prompt)
    else:
        ai_output = generate_python_from_openai(full_prompt)

    files = _parse_files_from_ai_output(ai_output)
    if not files:
        raise RuntimeError(
            "No files parsed from AI output. "
            "Ensure AI output contains file markers: === FILE: path ==="
        )

    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="fusional-mcp-")
    os.makedirs(out_dir, exist_ok=True)

    for path, content in files.items():
        dest = os.path.join(out_dir, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)

    # Optionally build Docker image
    build_result = None
    if build:
        if image_tag is None:
            import time
            image_tag = f"fusional-mcp:{int(time.time())}"
        
        cmd = ["docker", "build", "-t", image_tag, out_dir]
        proc = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603
        build_result = {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
            "image_tag": image_tag
        }

    return {
        "out_dir": out_dir,
        "files": list(files.keys()),
        "build_result": build_result
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Python from AI and execute on FusionAL server"
    )
    parser.add_argument("prompt", help="Task prompt for the AI")
    parser.add_argument("--provider", choices=["openai", "claude"], default="claude")
    parser.add_argument("--no-docker", dest="use_docker", action="store_false")
    parser.add_argument("--timeout", type=int, default=5)
    args = parser.parse_args()

    out = generate_and_execute(
        args.prompt,
        provider=args.provider,
        timeout=args.timeout,
        use_docker=args.use_docker
    )
    print("--- Generated Code ---")
    print(out["generated_code"])
    print("\n--- Execution Result ---")
    print(json.dumps(out["execution_result"], indent=2))
