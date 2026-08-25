"""End-to-end tests (T-012, T-020): real Streamable HTTP transport, real
MCP client, and for domain_intel, real RDAP/crt.sh network calls too.

Spins tools/imports_mcp/server.py as a subprocess on a dedicated test port
and connects with the official MCP client. This is what actually proves
the T-004 transport decision (and the T-020 network wiring) works, not
just that the underlying Python functions are correct - those are already
covered without paying for a server in test_server_contract.py and
test_domain_intel.py.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

TOOLS_DIR = Path(__file__).resolve().parent.parent


def _pick_free_port() -> int:
    """Ask the OS for an unused port instead of hardcoding one — a fixed port
    makes concurrent test runs (or an unrelated local service) flaky, per
    Qodo's finding on this test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_for_server(proc: subprocess.Popen, port: int, timeout: float = 10.0) -> None:
    """Poll for the port opening, but fail fast (with the captured output) if
    the child process has already exited — a successful TCP connect alone
    doesn't prove *our* server is what's listening, and waiting out the full
    timeout on a dead child just makes failures slower to diagnose."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(
                f"imports-mcp server exited early (code {proc.returncode}) "
                f"before opening port {port}:\n{output}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"imports-mcp server never opened port {port}")


@pytest.fixture(scope="module")
def running_server():
    port = _pick_free_port()
    server_url = f"http://127.0.0.1:{port}/mcp"
    env = os.environ.copy()
    env["IMPORTS_MCP_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "imports_mcp.server"],
        cwd=str(TOOLS_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server(proc, port)
        yield server_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _call_tool(url: str, name: str, arguments: dict):
    async with streamable_http_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool(name, arguments)
            return tools, result


async def _call_parse_message(url: str, fixture: str):
    return await _call_tool(url, "parse_message", {"fixture": fixture})


def test_parse_message_reachable_over_streamable_http(running_server):
    tools, result = anyio.run(_call_parse_message, running_server, "03-legitimate.eml")

    assert "parse_message" in [t.name for t in tools.tools]
    assert not result.is_error
    assert result.content
    assert "priya.nair@universal-imports.example" in result.content[0].text


def test_unknown_fixture_returns_error_over_the_wire(running_server):
    _, result = anyio.run(_call_parse_message, running_server, "nope.eml")
    assert result.is_error
    assert "Unknown fixture" in result.content[0].text


def test_domain_intel_reachable_over_streamable_http(running_server):
    """Real RDAP/crt.sh calls, not mocked - proves the whole path is wired,
    not just the HTTP transport. Deliberately asserts on structure only
    (domain echoed back, both sections present), never on live content: a
    volatile upstream value (registrar name, RDAP/crt.sh being reachable at
    all) would make this test only as reliable as those services, exactly
    the flakiness domain_intel's own graceful-degradation contract exists
    to route around - is_error stays False either way, which is what this
    test is actually here to prove."""
    tools, result = anyio.run(_call_tool, running_server, "domain_intel", {"domain": "google.com"})

    assert "domain_intel" in [t.name for t in tools.tools]
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["domain"] == "google.com"
    assert "available" in payload["rdap"]
    assert "available" in payload["cert"]


def test_domain_intel_empty_domain_returns_error_over_the_wire(running_server):
    _, result = anyio.run(_call_tool, running_server, "domain_intel", {"domain": ""})
    assert result.is_error


def test_url_reputation_reachable_over_streamable_http(running_server):
    """Real URLhaus call, not mocked - URLhaus (unlike crt.sh) has been
    reliably up throughout T-003/T-021, so unlike domain_intel's test this
    one can assert on the actual verdict, not just reachability."""
    tools, result = anyio.run(_call_tool, running_server, "url_reputation", {"url": "https://example.com/"})

    assert "url_reputation" in [t.name for t in tools.tools]
    assert not result.is_error
    assert "not listed" in result.content[0].text


def test_url_reputation_empty_url_returns_error_over_the_wire(running_server):
    _, result = anyio.run(_call_tool, running_server, "url_reputation", {"url": ""})
    assert result.is_error
