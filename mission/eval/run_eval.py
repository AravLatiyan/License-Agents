#!/usr/bin/env python3
"""mission/eval/run_eval.py — T-042 CLI entrypoint.

Runs the real `universal-imports` agent against every fixture in
mission/eval/fixtures/ and reports gate-trigger accuracy / false-positive
rate (see eval_lib.py's module docstring for the full metric definition and
why it is not "agent verdict accuracy").

This script itself is the opt-in boundary — it is never invoked by `pytest`
and has no effect on the normal test suite. Requires:
  - TrueForge running locally with the `universal-imports` agent already
    registered (harness/README.md's `POST /api/v1/agents` step) — this
    script does not register the agent itself, same assumption
    harness/test/approval-gate-verification/verify-approval-gate.sh makes
    about the gate wiring it verifies.
  - A model provider configured (PLAN.md §5) — without one, every fixture
    fails with the same HTTP 422 T-015/T-023/T-024 already hit, and this
    script reports that plainly rather than fabricating a result.

Usage:
    python mission/eval/run_eval.py [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lib import (  # noqa: E402
    FixtureResult,
    Report,
    agent_name,
    evaluate_fixture,
    gated_tool_names,
    load_fixtures,
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "results.json"


def _result_to_dict(result: FixtureResult) -> dict:
    return {
        "fixture_name": result.fixture_name,
        "label": result.label,
        "predicted_positive": result.predicted_positive,
        "resolved_gated_tools": result.resolved_gated_tools,
        "error": result.error,
    }


def _print_summary(results: list[FixtureResult], report: Report) -> None:
    print(f"\n{'fixture':<20} {'label':<6} {'predicted':<10} {'gated tools'}")
    print("-" * 70)
    for r in results:
        predicted = "FAILED" if r.predicted_positive is None else ("positive" if r.predicted_positive else "negative")
        print(f"{r.fixture_name:<20} {r.label:<6} {predicted:<10} {', '.join(r.resolved_gated_tools)}")

    print("\n--- gate-trigger evaluation (T-042) ---")
    print("Metric definition: predicted positive = >=1 gated tool proposed")
    print("(quarantine/notify_impersonated/create_block_rule/file_abuse_report);")
    print("this is NOT a three-way VerdictLabel match - see eval_lib.py's docstring.\n")
    print(f"Total fixtures:  {report.total_fixtures}")
    print(f"Scored:          {report.total_scored}")
    print(f"Failed (excluded from metrics): {len(report.failed)}")
    if report.failed:
        provider_failures = [r for r in report.failed if r.error and "422" in r.error]
        print(f"  of which HTTP 422 (model provider not configured, PLAN.md §5): {len(provider_failures)}")
        for r in report.failed:
            print(f"  - {r.fixture_name}: {r.error}")
    print(f"TP={report.true_positives} TN={report.true_negatives} "
          f"FP={report.false_positives} FN={report.false_negatives}")
    if report.gate_trigger_accuracy is None:
        print("gate_trigger_accuracy: N/A (nothing scored)")
    else:
        print(f"gate_trigger_accuracy: {report.gate_trigger_accuracy:.3f}")
    if report.false_positive_rate is None:
        print("false_positive_rate:   N/A (no ham fixtures scored)")
    else:
        print(f"false_positive_rate:   {report.false_positive_rate:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    fixtures = load_fixtures()
    agent = agent_name()
    gated_tools = gated_tool_names()

    # Printed as each fixture finishes, not batched at the end - a real run
    # against a live model provider can take many seconds per fixture, and a
    # batched-only summary left the terminal silent long enough to look hung
    # (found by actually running this against no TrueForge instance: each of
    # 40 sequential connection-refused failures took several seconds, and
    # nothing printed until every one of them had).
    results = []
    for i, fixture in enumerate(fixtures, start=1):
        result = evaluate_fixture(fixture, agent=agent, gated_tools=gated_tools)
        results.append(result)
        status = "FAILED" if result.predicted_positive is None else (
            "positive" if result.predicted_positive else "negative"
        )
        detail = result.error if result.error else ", ".join(result.resolved_gated_tools)
        print(f"[{i}/{len(fixtures)}] {fixture.name} ({fixture.label}) -> {status}  {detail}", flush=True)

    from eval_lib import score

    report = score(results)
    _print_summary(results, report)

    output_payload = {
        "agent": agent,
        "gated_tools": sorted(gated_tools),
        "metric_definitions": {
            "gate_trigger_accuracy": "(true_positives + true_negatives) / total_scored",
            "false_positive_rate": "false_positives / total_ham_scored",
            "note": "NOT a three-way VerdictLabel match - see eval_lib.py module docstring",
        },
        "results": [_result_to_dict(r) for r in results],
        "gate_trigger_accuracy": report.gate_trigger_accuracy,
        "false_positive_rate": report.false_positive_rate,
        "total_fixtures": report.total_fixtures,
        "total_scored": report.total_scored,
        "true_positives": report.true_positives,
        "true_negatives": report.true_negatives,
        "false_positives": report.false_positives,
        "false_negatives": report.false_negatives,
    }
    args.output.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
    print(f"\nWrote machine-readable results to {args.output}")

    return 0 if not report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
