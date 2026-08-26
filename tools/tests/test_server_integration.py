"""End-to-end test (T-012): real Streamable HTTP transport, real MCP client.

Spins tools/imports_mcp/server.py as a subprocess on a dedicated test port,
connects with the official MCP client, and calls parse_message for real.
This is what actually proves the T-004 transport decision works, not just
that the underlying Python function is correct (test_server_contract.py
already covers that without paying for a server).
"""

from __future__ import annotations

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


async def _call_parse_message(url: str, fixture: str):
    async with streamable_http_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("parse_message", {"fixture": fixture})
            return tools, result


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
