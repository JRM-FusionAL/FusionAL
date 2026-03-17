"""
FusionAL Test Script

Simple tests to verify FusionAL is working correctly.
Run this after starting the FastAPI server with: uvicorn main:app --reload --port 8009
"""

import requests
import json

SERVER_URL = "http://localhost:8009"
REQUEST_TIMEOUT = 15


def test_health():
    """Test the health endpoint."""
    print("🔍 Testing health endpoint...")
    try:
        resp = requests.get(f"{SERVER_URL}/health", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        print("✅ Health check passed!")
        print(json.dumps(resp.json(), indent=2))
        return True
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False


def test_execute_simple():
    """Test simple code execution without Docker."""
    print("\n🔍 Testing simple execution (no Docker)...")
    code = "print('Hello from FusionAL!')\nprint(2 + 2)"
    
    try:
        resp = requests.post(
            f"{SERVER_URL}/execute",
            json={
                "language": "python",
                "code": code,
                "timeout": 5,
                "use_docker": False
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
        print("✅ Simple execution passed!")
        print(f"Output: {result['stdout']}")
        print(f"Return code: {result['returncode']}")
        return True
    except Exception as e:
        print(f"❌ Simple execution failed: {e}")
        return False


def test_execute_docker():
    """Test code execution with Docker sandboxing."""
    print("\n🔍 Testing Docker execution...")
    code = "import sys\nprint('Hello from Docker!')\nprint(f'Python version: {sys.version}')"
    
    try:
        resp = requests.post(
            f"{SERVER_URL}/execute",
            json={
                "language": "python",
                "code": code,
                "timeout": 10,
                "use_docker": True,
                "memory_mb": 128
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
        print("✅ Docker execution passed!")
        print(f"Output: {result['stdout']}")
        print(f"Return code: {result['returncode']}")
        return True
    except Exception as e:
        print(f"❌ Docker execution failed: {e}")
        print("   Make sure Docker Desktop is running!")
        return False


def test_catalog():
    """Test the MCP server catalog endpoint."""
    print("\n🔍 Testing catalog endpoint...")
    try:
        resp = requests.get(f"{SERVER_URL}/catalog", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        print("✅ Catalog check passed!")
        print(f"Total servers: {result['total']}")
        if result['servers']:
            print("Registered servers:")
            for name, info in result['servers'].items():
                print(f"  - {name}: {info.get('description', 'No description')}")
        else:
            print("  No servers registered yet")
        return True
    except Exception as e:
        print(f"❌ Catalog check failed: {e}")
        return False


def test_register():
    """Test registering a new MCP server."""
    print("\n🔍 Testing server registration...")
    try:
        resp = requests.post(
            f"{SERVER_URL}/register",
            json={
                "name": "test-server",
                "description": "Test MCP server for validation",
                "url": "docker://test-mcp-server",
                "metadata": {"version": "1.0.0", "tools": ["test_tool"]}
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
        print("✅ Server registration passed!")
        print(json.dumps(result, indent=2))
        return True
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            print("⚠️  Server already registered (expected on second run)")
            return True
        print(f"❌ Server registration failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Server registration failed: {e}")
        return False


def run_all_tests():
    """Run all tests in sequence."""
    print("=" * 60)
    print("🚀 FusionAL Test Suite")
    print("=" * 60)
    
    results = []
    
    # Basic tests
    results.append(("Health Check", test_health()))
    results.append(("Simple Execution", test_execute_simple()))
    results.append(("Docker Execution", test_execute_docker()))
    results.append(("Catalog Check", test_catalog()))
    results.append(("Server Registration", test_register()))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! FusionAL is working correctly.")
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")


if __name__ == "__main__":
    run_all_tests()
