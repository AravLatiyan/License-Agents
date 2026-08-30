# mission/eval — T-042 evaluation harness

Evaluates the real `universal-imports` TrueForge agent against 40 real emails
(20 phishing, 20 legitimate) and reports **gate-trigger accuracy** and
**false-positive rate**. See `eval_lib.py`'s module docstring for the full
design writeup — this file is the practical "how do I run it" reference.

## Why "gate-trigger accuracy," not "agent verdict accuracy"

There is no live producer of `contracts/events.ts`'s three-way
`malicious | suspicious | legitimate` `VerdictLabel` anywhere in this
project — T-037's own translator (`harness/translate/translate.ts`)
deliberately never emits one: "the stream carries only the model's prose;
parsing a label out of prose is inventing semantics." This harness agrees,
and doesn't parse prose either.

Instead it reads TrueForge's real `tool.approval_required` wire event
(confirmed live, T-002/§6, re-verified field-by-field against a running
server's `openapi.json` in T-037, 2026-08-29). That event only ever fires
for a tool named in `harness/agent.json`'s `require_approval_for_tools`
list — so its occurrence is direct proof the agent proposed one of the four
gated actions (`quarantine`, `notify_impersonated`, `create_block_rule`,
`file_abuse_report`), with no invented classifier layered on top.

```
predicted positive = >=1 gated tool proposed for that fixture
predicted negative = no gated tool proposed
ground truth positive = fixture from phishing_pot ("phish")
ground truth negative = fixture from SpamAssassin easy_ham ("ham")

gate_trigger_accuracy = (true_positives + true_negatives) / total_scored
false_positive_rate   = false_positives / total_ham_scored
```

A fixture whose evaluation itself fails (network error, non-2xx response,
the model provider being unconfigured) is excluded from both metrics and
reported separately — never folded into "negative."

## Fixtures

`fixtures/phish/` — 20 real samples from
[phishing_pot](https://github.com/rf-peixoto/phishing_pot) (`sample-1.eml`
through `sample-20.eml`, MIT-licensed, actively collected).

`fixtures/ham/` — 20 real samples from the
[SpamAssassin public corpus](https://spamassassin.apache.org/old/publiccorpus/)'s
`20030228_easy_ham.tar.bz2` (`00001.eml` through `00020.eml`, Apache-licensed,
the project's own established false-positive baseline).

Both are real, historical, already-published research corpora — not
synthetic and not the Range's own fictional-brand fixtures (`range/fixtures/`,
T-061, which stay separate and are never used here). §13 Tier 2 explicitly
scopes these to evals only, never the demo.

## Running it

Prerequisites (same as `harness/test/approval-gate-verification/`):

```bash
npx @truefoundry/trueforge &                    # localhost:8790
curl -X POST http://localhost:8790/api/v1/agents -d @harness/agent.json
# a model provider configured + spend cap set, in TrueForge's settings UI
```

Then:

```bash
python mission/eval/run_eval.py
```

Prints progress per fixture as it runs (a real multi-tool-call turn can take
a while — nothing about this loop batches output until the end), then a
summary table, then writes `mission/eval/results.json`.

Exits `0` if every fixture was scored, `1` if any failed outright (check the
"Failed" section of the printed summary for why — a `main` HTTP 422 usually
means the model provider isn't configured, PLAN.md §5).

## What's verified vs. assumed

Confirmed against this project's own prior live verification (T-002/§6,
T-037/2026-08-29): `POST /sessions`, `POST /sessions/{id}/turns` with
`stream: true` → SSE, the `tool.approval_required` / `model.message` wire
shapes and their `ToolCallRef` correlation.

**Not independently re-verified this session** (no local TrueForge instance
was running, and `trueforge.dev` was unreachable from this environment):
the exact JSON body `POST /sessions` expects to bind a session to an agent
by name, and the exact `input` shape for a turn's *first* message (only the
*resume* shape, `user.tool_approval`, is documented anywhere in this repo).
Both are isolated to one function each in `eval_lib.py`
(`create_session()`, `run_turn_and_observe()`) — fix there first if a live
run shows a different shape.

## Safety

This harness never resumes a paused gate. The instant `tool.approval_required`
fires, it already has its answer and stops reading the stream — no
`user.tool_approval` is ever posted, so the underlying action (a real
quarantine tag, a real SMTP send, a real abuse-report email) never executes
against a historical corpus email. Same spirit as CLAUDE.md trap #6, applied
to evaluation rather than the live demo.

## Tests

`python -m pytest mission/eval/tests/` — fully mocked, never touches a real
TrueForge instance. `run_eval.py` itself is the only opt-in path to a live
40-fixture run; it is never invoked by the normal test suite.
