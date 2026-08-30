# UNIVERSAL IMPORTS

An email counter-intelligence agent. Forward it anything asking you to click, pay, reset, or
approve. It detonates the payload in a sandbox, sends three subagents after who's really behind
it, and comes back with a verdict and a set of proposed actions — **none of which happen until a
human grants the licence for each one.**

Built on [TrueForge](https://trueforge.dev), TrueFoundry's agent runtime. See `PLAN.md` for the
full plan, decisions, and task history, and `CLAUDE.md` for the project's working rules.

## Architecture

```
  message arrives (a named fixture, passed to parse_message — see note below)
        │
   ┌────▼──────────────────────────────────────────┐
   │ NORMALISE — RFC822 parse, no network          │
   │ headers · SPF/DKIM/DMARC · URLs · attachments │
   └────┬──────────────────────────────────────────┘
        │  TrueForge lead agent
   ┌────▼───────────┬────────────────┬─────────────┐
   │ INFRASTRUCTURE │   IDENTITY     │   HISTORY   │  ← 3 subagents, parallel
   │ RDAP age       │ display-name   │ prior mail  │
   │ cert age       │  vs reply-to   │ from this   │
   │ URLhaus        │ lookalike dom. │ person/dom. │
   │ + DETONATION ──┤                │             │
   └────┬───────────┴────────────────┴─────────────┘
        │
   ┌────▼──────── DETONATION (current: text-mode) ─┐
   │ redirect chain · HTML parse · form targets ·  │
   │ asks-for-password? — no browser, no screenshot│
   └────┬──────────────────────────────────────────┘
        │
   ┌────▼──────────────────────────────────────────┐
   │ VERDICT + EVIDENCE  →  4 PROPOSED ACTIONS     │
   └────┬──────────────────────────────────────────┘
        │
   ┌────▼── 🔶 FOUR SEQUENTIAL LICENCE GATES ──────┐
   │ TrueForge pauses on each approval-marked tool │
   │ call and shows the JSON request.              │
   │  1. quarantine        → [Allow] [Deny]        │
   │  2. notify impersonated → [Allow] [Deny]      │
   │  3. block rule        → [Allow] [Deny]        │
   │  4. abuse report      → [Allow] [Deny]        │
   └────┬──────────────────────────────────────────┘
        │
   execute granted · speak the verdict
```

**What's actually implemented vs. what the architecture aims at**, so this diagram doesn't
overclaim:

- **Detonation is text-mode only.** A Daytona-sandboxed headless-Chromium path with a real
  screenshot was the original design and remains the goal, but it was never built — `tools/imports_mcp/detonate.py`
  and `harness/detonate.js` both do redirect-chain-follow + HTML parse only, no browser, no
  sandbox execution. See `PLAN.md` §5 (T-035) for why: no Daytona API key is configured, and
  TrueForge exposes no snapshot/warm-pool mechanism the "second run must be fast" requirement
  needs.
- **Mailbox intake is not wired up.** There is no IMAP/maildir watcher. The only entry point is
  `parse_message(fixture)`, which reads a named file out of `tools/fixtures/` — the pipeline
  is fully real from that point on, but a message has to already exist as a fixture to run it.
- **All four gated tools now exist, but `create_block_rule`'s store is write-only.** It shipped
  in T-032 (PR #90) and is a real, tested tool — but nothing in this repository ever reads those
  rules back, so no mail is actually blocked. That is a deliberate scope call, not an oversight:
  Mailpit is a mail *catcher* with no rule or policy endpoint to install a pattern into, and
  nothing in `tools/`, `harness/`, `cockpit/` or `mission/` reads a blocklist. The tool records a
  decision durably; it does not enforce one, and its own module docstring says so in capitals. See
  `PLAN.md` §6 (T-032, Option B).

**The Daytona sandbox catch, for when that path gets built:** Daytona is remote and cannot reach
a Range running on your laptop's `localhost`. The fake portal would need to run *inside the
sandbox itself* — zero networking, works offline, works on a judge's machine. Today, with
detonation in text-mode, this doesn't yet apply in practice.

## Repo layout

```
/contracts     shared TypeScript types + fixture event stream (Owner 1/2/3 shared)
/harness       TrueForge config (agent.json), the turn-stream → mission.* translator,
               text-mode detonation
/tools         the imports-mcp MCP server: normaliser, intel APIs (RDAP/crt.sh/URLhaus),
               correspondence history, detonation, and all four gated actions
               (quarantine, notify_impersonated, create_block_rule, file_abuse_report —
               create_block_rule's rule store is write-only, see the note above)
/cockpit       the UI — a Vite/React app that renders a live mission
/mission       Range fixtures, fake-portal, skills, the T-042 evaluation harness
/range         Docker Compose for Mailpit (mail capture) + the fake phishing portal
PLAN.md        the plan, task board, decisions, and history — read this for "why"
CLAUDE.md      working rules this project holds itself to
```

## Quickstart (clean clone)

Requirements: Docker, Python 3.11+, Node 22+, and `npx` access to
`@truefoundry/trueforge`. **On Windows, run TrueForge from WSL2** — it segfaults on native
Windows (`harness/README.md` has the full note).

Every step below assumes you start at the **repo root** each time — each numbered block ends by
returning there (`cd ..`) so you can run them in order in one shell without losing track of where
you are.

**1. Bring up the Range** — a real, self-contained mailbox + a fictional phishing portal:

```bash
cd range
docker compose up -d
bash seed.sh   # or seed.ps1 on Windows — posts the 20 fixtures into Mailpit
cd ..
```

Mailpit's UI is now at `localhost:8025`. The fake portal listens on `localhost:8080` — today
that's a plain host-reachable server you can open in a browser to look at by hand; the seeded
fixtures that point at it are **not** detonated by the pipeline's default run, since
`detonate()`'s SSRF guard refuses loopback/private targets unless a test-only bypass is passed
explicitly (see `tools/tests/test_detonate.py`). Wiring a real sandboxed detonation path against
this portal is the Daytona work described above, not yet built.

**2. Set up `tools/` (the MCP server)**

```bash
cd tools
python -m venv .venv
.venv/Scripts/activate        # .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cd ..
cp .env.example .env          # fill in URLHAUS_AUTH_KEY if you have one; everything else
                               # defaults to the local Range
```

Run its test suite from the repo root (the root `pytest.ini` wires `tools/` onto
`PYTHONPATH`) — this also needs the `tools/.venv` from the step above active:

```bash
pytest
```

**3. Start TrueForge and register the agent**

```bash
npx @truefoundry/trueforge   # localhost:8790
curl -X POST http://localhost:8790/api/v1/agents -H "Content-Type: application/json" \
  -d @harness/agent.json
```

Register `tools/imports_mcp`'s MCP server as a connector in TrueForge's own settings UI, then
configure a model provider **with a spend cap** — also in that UI, never pasted into a chat or
committed to this repo.

Run the harness's own tests:

```bash
cd harness
npm install
npm test
cd ..
```

**4. Run the Cockpit UI**

```bash
cd cockpit
npm install
npm run dev
cd ..
```

By default it plays back a static fixture (`contracts/fixtures/mission-happy-path.json`) so the
UI is fully explorable without a live TrueForge connection. Note: this quickstart's own
verification (`PLAN.md`, T-065) ran `npm run build` in place of leaving `npm run dev` running as
a server — see that entry for exactly what was and wasn't executed.

## Safety rules

- The sandbox holds no credentials and has no route back to real infrastructure.
- Remote images are never rendered (tracking-pixel confirmation risk).
- Attachments are hashed (SHA-256) and never executed. Reputation lookup against that hash is
  not wired up yet — no tool performs it today, so an attachment's hash is evidence recorded, not
  evidence checked against anything.
- Fixtures are de-fanged (`hxxp://`) and use only fictional brands ("Northgate Trust",
  "Meridian Courier") — never a real company.
- Live-mailbox tests are opt-in only and never run by default (`RUN_LIVE_*` environment
  variables) — the normal `pytest`/`npm test` runs never touch a real network.
- Every gated action (`quarantine`, `notify_impersonated`, `create_block_rule`,
  `file_abuse_report`) stops for an explicit human licence before it can execute.

## How TrueForge and Qodo made this project possible

Neither tool was incidental. TrueForge supplied the runtime this system is an integration
*with* — without it there is no turn stream, no tool execution, and nothing to pause. Qodo
supplied adversarial pressure at the PR boundary, and repeatedly found defects that compiled,
passed the tests, and would have shipped.

### TrueForge — the runtime that made the behaviour real

TrueForge runs the agent loop. This repo configures it and builds on top of it; it does not
reimplement it. `harness/agent.json` is the whole configuration surface: model
(`anthropic/claude-sonnet-5`, `temperature 0.2`, `max_tokens 16384`), a single `imports-mcp`
connector, and the line that makes the safety story work —

```json
"require_approval_for_tools": ["quarantine", "notify_impersonated",
                               "create_block_rule", "file_abuse_report"]
```

Those four names are the only place gating is declared. Every gated tool's docstring in
`tools/imports_mcp/server.py` says so explicitly — *"Approval is the harness's job, never checked
here"* — and no approval logic exists in the tool layer at all. `harness/agent-config.test.js`
pins the list, its order, and the fact that the five read-only tools are **not** in it, because a
typo in a gate name is not a loud failure: TrueForge accepts `require_approval_for_tools` entries
for tools that do not exist, so `"quarentine"` would be schema-valid and would silently ungate the
real one.

**The boundary we built.** TrueForge's wire stream is raw: `model.message`,
`tool.approval_required`, `tool.response`, `turn.done` and eight other types.
`harness/translate/translate.ts` turns those into the `mission.*` events in `contracts/events.ts`
that the cockpit renders. Two decisions define it:

- **It never parses prose into structure.** `turn.done` carries the model's plain English, and
  `contracts/events.ts` defines a three-way `VerdictLabel` — but the translator deliberately
  never emits `mission.verdict`, because doing so would mean *"inventing a verdict TrueForge never
  actually rendered"*. The same reasoning blocks the identity lane: emitting
  `lookalike_domain: false` would render as "no lookalike detected" for a check nothing ran.
  `VerdictLabel` therefore has **no live producer** anywhere in this project, which is also why
  the T-042 evaluation harness scores `gate_trigger_accuracy` — did the agent propose a gated
  action — rather than an invented classifier's agreement.
- **Structure comes from correlating real tool calls.** `tool.approval_required` carries only
  `ToolCallRef {id, source_event_id}` — no tool name. The translator remembers each
  `model.message`'s own event id alongside its calls and resolves a gate only when **both** the
  call id and `source_event_id` match, failing closed otherwise (`translate.ts:339-350`). That is
  what lets a human be shown the actual tool and its decoded arguments instead of an opaque
  reference.

**The licence flow, end to end:** the agent calls a gated tool → TrueForge pauses the call and
emits `tool.approval_required` → the translator emits `mission.approval_required` carrying that
gate's own `tool_call_id` → the cockpit renders LICENCE REQUIRED with the resolved action →
Allow/Deny posts a `user.tool_approval` resume as a new streaming turn → `resolveGate()` releases
the next queued gate → the action settles as `mission.action_executed`, or the mission ends
`mission.complete` / `mission.failed`. Gates are held **one outstanding at a time**, not merely
capped at four.

**What this bought for the qualifying test** — a judge must see the harness reach a real tool, run
real code, and stop for a person. Against a live TrueForge 0.1.4 instance the agent registered
(`201`), all nine MCP tools were discovered, and on fixture `sample-11.eml` a real
`tool.approval_required` fired carrying three proposed actions. Nothing was resumed: the harness
stops reading at the gate, so all three stayed parked and none executed. Across the full 40-fixture
evaluation, **no approval was ever resumed and no gated action ever ran**.

**Honest boundaries.** The translator and cockpit are unit-tested (69 and 62 tests) but have never
been driven from a live TrueForge stream — the live path was exercised by the evaluation harness
instead, and `translate.ts`'s own header records which behaviours are therefore assumptions.
Reconnect-resume exists as `cockpit/src/resumableStream.ts` but is wired to nothing, because
TrueForge publishes no documented cursor field. No `user.tool_approval` has ever been posted to a
real server. And the live gate arrived **batched** — three calls in one approval event — which is
not the "four sequential gates" the architecture above describes; the translator's queue is the
mitigation, but it has not yet met a live batched event. TrueForge supplied the runtime and the
event surface; it does not by itself make any of this safe. The controls are ours, and so are the
gaps.

**Still credential-blocked:** the Daytona sandbox (`PLAN.md` §5, T-035) and `URLHAUS_AUTH_KEY`.
Notably, Daytona turned out *not* to be on the critical path — TrueForge standalone ships a local
bubblewrap sandbox that needs `bwrap`, `socat` and `rg` and no credential at all. It is invisible
from every catalog and settings endpoint, appearing only in `GET /api/v1/capabilities`, so a
missing `socat` failed the boot probe silently and made every symptom point at Daytona instead.

### Qodo — adversarial review, not a style checker

Qodo reviewed every PR. Across the project it raised roughly 150 findings; 132 were resolved, 9
were dismissed with written reasoning. **Qodo found and re-verified these issues; every fix was
written by a human owner or an agent working as one.** Qodo never modified code.

The pattern worth noticing is that the strongest findings were all in code that compiled and
passed its tests.

**Approval resolved to the wrong tool call** (PR #73, re-raised #74 · T-037). The translator
joined a `ToolCallRef` to its `model.message` using only `call.id`, ignoring `source_event_id` —
*"the field was named in a comment and then ignored."* Tool-call ids are unique only within the
message that issued them, so a stale id could supply the name and arguments for a gate: **one
action shown to the human while a different one is approved**, the exact failure the licence
mechanism exists to prevent. Fixed to require both ids and fail closed. Qodo marked both findings
resolved; harness suite 78/78 at merge.

**The same class, reintroduced one layer up** (PR #85 · T-046). The cockpit's approval panel took
`approval.tool_calls[0]`, so with several calls in one event **gate 2 resumed gate 1's action**.
Fixed by adding `tool_call_id` to `ApprovalRequiredEvent` and carrying it per gate. The project's
own note is blunt about why tests missed it: *"Qodo caught it; no test would have, because every
existing fixture had one call per approval."*

**Qodo rejecting our first answer** (PR #73 finding #3). One approval event carrying several calls
emitted every gate simultaneously. The first response was a comment documenting the limitation,
arguing the stream carries no "approval resolved" signal. A second Qodo pass rejected that —
*"documents the limitation but does not prevent the invalid state"* — and the fix became real
serialisation: `resolveGate(gateIndex)`, one gate outstanding, extras queued. The repo records the
concession: *"which was the right call."*

**A failure that rendered as still running** (PR #71 · T-037). `mission.failed` was missing from
the cockpit's `KNOWN_TYPES`, so every valid failure event was rejected before reaching the plan
tree; separately, terminal-state derivation checked only `mission.complete`, leaving a failed
mission active forever. Both fixed.

**A measurement that would have been silently invalid** (PR #76 · T-042). The evaluation harness
submitted each fixture's raw RFC822 text, but the agent's prompt requires `parse_message(fixture)`
first — and that tool only accepts a bare filename already in `tools/fixtures/`, a three-file
whitelist unrelated to the eval corpus. Every eval turn would have failed the parser call or,
worse, *"silently analyzed one of those 3 unrelated fixtures while scoring the result against the
intended fixture's label."* Two sibling findings were the same shape: a truncated SSE stream became
a false negative, and a bare `TimeoutError` while iterating an open stream would have aborted the
whole 40-fixture loop. All fixed with regression tests.

**Qodo catching a fix for overreaching** (PR #96 · T-074). A repair for gated-action failures
reported them as `FAILED`, while the code's own comment admitted an unreadable reply can follow a
side effect that really happened. These four actions are not idempotent — an operator told
*"notify_impersonated FAILED"* may reasonably send it again, to a real person. Reworded to
`UNCONFIRMED`, stating the outcome is unknown in both directions and quoting the reply so the
operator judges it. The rationale now lives in the code (`translate.ts:186-213`).

**And the branch that reintroduced its own headline bug** (PR #99 · T-042). A branch whose entire
purpose was *"a failed turn must never be scored as a negative"* still accepted a `turn.done` with
a missing or malformed status as success — recreating the exact silent metric corruption it
existed to fix. Sharper still: four tests in the same suite were sending a statusless `turn.done`
as their happy path, so the suite could never have caught it. Qodo found it by reading the
module's own documented claim against the code's actual acceptance condition.

**Findings were treated as hypotheses, not orders.** Qodo's suggestion to synthesise
`Authentication-Results` headers into the SpamAssassin ham corpus was declined twice — RFC 5451
was published in 2009 and those messages are from 2002, so adding one would assert a specific,
false security-check outcome on real historical mail. A rule about detonating against `localhost`
was declined four times, on the grounds that its stated reason is a network-reachability fact
about a *remote* sandbox and does not apply to an in-process test fixture. When a Qodo dashboard
kept showing a fixed finding as open, the evidence was checked line-by-line, shown to be stale,
and the fix re-proved by running the real tool unmocked.

**Where the loop does not reach.** A separate audit of already-merged code later found two real
security defects no Qodo pass had ever raised — `notify_impersonated` would mail a model-supplied
address through any configured SMTP host, and a granted licence whose action then failed could
leave an operator watching "executing…" indefinitely. Both had passing tests; one test actively
*asserted the buggy behaviour*. The lesson is recorded in `PLAN.md` §8: **Qodo reviews diffs, not
systems.** Neither of those defects is attributable to Qodo, and the same holds for the
test-suite deadlock in T-072, which came from a full-suite run rather than any review.

### The development loop

1. Build the smallest implementation that could work.
2. Run the deterministic suites.
3. Have Qodo review the actual PR HEAD — not a description of it.
4. Treat each finding as a hypothesis and verify it independently against the code.
5. Fix the genuine ones; decline the rest **in writing**, with evidence.
6. Add regression tests, and mutation-check the ones that matter — a fix that only satisfies the
   happy path is not a fix.
7. Re-run the affected suite and the full suite.
8. Merge only once the final HEAD has been reviewed and is green.

Step 4 is the one that carried weight. This project executes irreversible actions — quarantining
mail, emailing an impersonated party, filing an abuse report with a registrar — behind a human
decision, over SMTP, against attacker-supplied URLs, with SSRF and DNS-pinning guards. In that
setting "the tests pass" establishes very little: several of the defects above had passing tests,
and one had a test defending the bug.

### What each system contributed

| System | Contribution | Why it mattered |
|---|---|---|
| **TrueForge** | Agent runtime, real turn stream, MCP tool execution, native approval pause and resume | Made the agent/harness interaction real rather than a static simulation — a gate that actually fires and actually stops |
| **Qodo** | Adversarial PR review, bug discovery, sustained regression pressure | Repeatedly caught issues that compilation and green test suites did not expose, including two separate instances of "the human approves a different action than the one displayed" |
| **Repository tests / mutation checks** | Deterministic verification (467 Python · 92 harness · 62 cockpit) | Converted findings into durable regressions and stopped fixes from merely satisfying the happy path |

### The lesson

The achievement here is not "we used an LLM and a code-review bot." It is the feedback loop the
two produced together. TrueForge made runtime behaviour observable and real, so claims about
gates, tool calls and failures could be checked against a wire rather than argued about. Qodo
challenged the implementation at the PR boundary, where a second reader is cheapest and a defect
is still free to fix. Tests and mutation checks turned those findings into regressions that
outlive the conversation that produced them. And the parts the loop *missed* — the defects only a
whole-system audit surfaced — are recorded just as plainly, because a review process you cannot
state the limits of is not one you can rely on.

## More detail

- `harness/README.md` — TrueForge config, the turn-stream translator, known Windows/WSL2 issues.
- `mission/eval/README.md` — the gate-trigger evaluation harness (T-042): how it measures
  accuracy without inventing a verdict classifier, and how to run it against a live agent.
- `PLAN.md` — everything else: the full task history, every design decision and why, and the
  demo script this project is built against.
