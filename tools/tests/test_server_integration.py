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
TEST_PORT = 8951
SERVER_URL = f"http://127.0.0.1:{TEST_PORT}/mcp"


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"imports-mcp server never opened port {port}")


@pytest.fixture(scope="module")
def running_server():
    env = os.environ.copy()
    env["IMPORTS_MCP_PORT"] = str(TEST_PORT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "imports_mcp.server"],
        cwd=str(TOOLS_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_port(TEST_PORT)
        yield SERVER_URL
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
