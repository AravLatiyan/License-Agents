"""Shared pytest configuration for the tools/ test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _allow_test_only_private_targets(monkeypatch):
    """detonate()'s `allow_private_network_targets=True` bypass additionally
    requires this env var (Qodo finding #5, PR #37 review — a bare function
    parameter alone was judged too easy to mistake for a production-safe
    option). Every test in this suite runs with it set, autouse so no test
    file needs to opt in individually — this covers test_detonate.py's own
    suite too once that stacked PR (#38) rebases on top of this change,
    without editing that file at all.

    Draws the same "test fixtures may target localhost, nothing else may"
    boundary the project already established twice for harness/
    detonate.test.js (PLAN.md §8, 2026-08-25) — a real deployment never
    sets this env var, so the bypass can't function outside a deliberately
    configured test run.
    """
    monkeypatch.setenv("IMPORTS_MCP_ALLOW_TEST_TARGETS", "1")
