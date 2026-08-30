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
sudo apt-get install -y bubblewrap socat ripgrep   # TrueForge's local sandbox needs all three
npx @truefoundry/trueforge &                       # localhost:8790
curl -X POST http://localhost:8790/api/v1/settings/mcp-servers   -H 'Content-Type: application/json'   -d '{"manifest":{"type":"remote","name":"imports-mcp","url":"http://127.0.0.1:8941/mcp","description":"..."}}'
curl -X POST http://localhost:8790/api/v1/agents -d @harness/agent.json
# a model provider configured + spend cap set, in TrueForge's settings UI
```

`agent.json` sets `config.sandbox.enabled: true`, so registering it needs a
sandbox. TrueForge standalone has a **local bubblewrap sandbox** that needs
no provider and no credential, but its boot probe requires `bwrap`, `socat`
and `rg` on Linux (`SRT_HOST_BINARIES_BY_PLATFORM`). Without them the probe
fails, `GET /api/v1/capabilities` reports `sandbox.enabled: false`, and
`POST /api/v1/agents` returns
`422 "sandbox is enabled but no sandbox provider is configured"` — a message
that points at Daytona even though Daytona is not needed. Install the three
packages instead; see PLAN.md §7.

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

Everything below is now confirmed against a **live TrueForge 0.1.4**
instance (2026-08-30), replacing the earlier "not independently re-verified"
note. The four shapes that note flagged were all wrong, and all are fixed:

| was | is | how it failed |
|---|---|---|
| `POST /sessions` | `POST /api/v1/sessions` | `404` |
| `{"agent_name": …}` | `{"agent": {"name": …}}` | `400 Unrecognized key: "agent_name"` |
| id at `payload["id"]` | id at `payload["data"]["id"]` | "carried no usable id" |
| `input` a single object | `input` an **array** of items | `400 expected array, received object` |

Each was confirmed by the server's own request validation, which runs
*before* the turn does — so pinning these down cost no model call. The
`tool.approval_required` / `model.message` wire shapes and their
`ToolCallRef` correlation were re-checked field-by-field against the live
`/api/v1/openapi.json` and are unchanged from T-002/T-037.

One correction carried over from that check: `mission.complete` is this
project's own Layer 2 translated event (`contracts/events.ts`), **not** a
TrueForge wire event — TrueForge's `TurnStreamingEvent` union has 12 types
and `turn.done` is the only turn-terminal one. `thread.done` is
deliberately not treated as turn-terminal here: it fires per thread, so a
delegated subagent finishing would end the read before the root agent had
proposed anything.

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
