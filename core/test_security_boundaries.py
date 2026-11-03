"""Regression checks for the gateway's code-execution and MCP auth boundaries."""

import asyncio

from fastapi.testclient import TestClient

from core.main import app
from core.mcp_transport import _downstream_client


def test_mounted_mcp_rejects_anonymous_initialize(monkeypatch):
    monkeypatch.setenv("API_KEY", "gateway-test-key")
    response = TestClient(app).post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 401


def test_host_code_execution_cannot_be_requested(monkeypatch):
    monkeypatch.setenv("API_KEY", "gateway-test-key")
    client = TestClient(app)
    response = client.post(
        "/execute",
        json={"code": "print('unsafe')", "use_docker": False},
        headers={"X-API-Key": "gateway-test-key"},
    )
    assert response.status_code == 400
    assert "Host execution is disabled" in response.json()["detail"]


def test_generated_server_cannot_opt_out_of_sandbox(monkeypatch):
    monkeypatch.setenv("API_KEY", "gateway-test-key")
    response = TestClient(app).post(
        "/generate",
        json={"prompt": "test", "sandbox": False},
        headers={"X-API-Key": "gateway-test-key"},
    )
    assert response.status_code == 400


def test_showcase_proxy_sends_its_interservice_key(monkeypatch):
    monkeypatch.setenv("SHOWCASE_MCP_API_KEY", "showcase-test-key")
    client = _downstream_client("api-integration-hub", 5.0)
    try:
        assert client.headers["X-API-Key"] == "showcase-test-key"
    finally:
        asyncio.run(client.aclose())


def test_generated_server_names_are_argv_safe():
    from core.main import _SAFE_SERVER_NAME, _slugify_server_name

    hostile = ["--privileged", "a:b,c", "x; rm -rf /", "../../etc", "", "----"]
    for prompt in hostile + ["Weather tools for Kentucky", "PDF → summary"]:
        assert _SAFE_SERVER_NAME.fullmatch(_slugify_server_name(prompt))
    for raw in ["-x-mcp", "a:b-mcp", "a,b-mcp", "a b-mcp", "A-mcp"]:
        assert not _SAFE_SERVER_NAME.fullmatch(raw)
