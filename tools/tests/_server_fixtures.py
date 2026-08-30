"""Shared subprocess/transport fixture for the server integration suites.

Split out of test_server_integration.py (Qodo PR #19 finding: "Live test
remains flaky") so the always-on, deterministic transport tests never share
a server subprocess with the live-network tests (test_server_integration_live.py).
PLAN.md §7 documents a reproducible httpx.ReadTimeout on a *later* test in
the same shared subprocess once a real network call has gone through it —
splitting the fixture scope by file means that stall, if it happens, can
only ever affect the opt-in live tests, never the deterministic ones CI/a
clean clone/a judge's machine actually runs by default.
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import tempfile
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


def _read_log(log_path: Path) -> str:
    """Best effort: a missing or unreadable log must never mask the real
    failure being reported alongside it."""
    try:
        return io.open(log_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return "(server log unavailable)"


def _wait_for_server(
    proc: subprocess.Popen, port: int, log_path: Path, timeout: float = 10.0
) -> None:
    """Poll for the port opening, but fail fast (with the captured output) if
    the child process has already exited — a successful TCP connect alone
    doesn't prove *our* server is what's listening, and waiting out the full
    timeout on a dead child just makes failures slower to diagnose.

    Reads the log from `log_path` rather than from a pipe: see the fixture
    below for why the server must never write into an unread pipe."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = _read_log(log_path)
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
    """Module-scoped: importing this fixture into two different test modules
    gives each its own subprocess instance, since pytest keys module-scoped
    fixtures by the requesting test's module, not by where the fixture is
    defined — that's the isolation this split depends on."""
    port = _pick_free_port()
    server_url = f"http://127.0.0.1:{port}/mcp"
    env = os.environ.copy()
    env["IMPORTS_MCP_PORT"] = str(port)
    log_path = Path(tempfile.mkdtemp(prefix="imports-mcp-test-")) / "server.log"
    # A FILE, never subprocess.PIPE. The server logs a line per request, and
    # nothing in this fixture reads that stream while the tests run — so with
    # a pipe the OS buffer fills after a handful of requests, the server
    # blocks forever inside write(), and every later session dies on
    # httpx.ReadTimeout. That is exactly the "flaky after N calls" failure
    # §7 logged twice (2026-08-26, 2026-08-30) and blamed on live network
    # calls; a live call only makes it happen sooner by logging more.
    # A file has no such buffer limit, and still keeps the output for
    # _wait_for_server and for a human reading a failure.
    with io.open(log_path, "w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "imports_mcp.server"],
            cwd=str(TOOLS_DIR),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_for_server(proc, port, log_path)
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


def call_tool(url: str, name: str, arguments: dict):
    """Sync wrapper — every call site was already doing `anyio.run(_call_tool, ...)`."""
    return anyio.run(_call_tool, url, name, arguments)
