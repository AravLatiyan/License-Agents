# UNIVERSAL IMPORTS

**An AI agent that investigates suspicious emails and then waits for you before doing anything about them.**

You hand it a phishing-style email (for example, "your CFO needs an urgent wire transfer").
It reads the message, looks up who is really behind the links and the sender, writes a
plain-English verdict, and proposes a few defensive actions — quarantine the message, warn
the person being impersonated, and so on. **None of those actions happen until a human
approves each one, individually.**

Built on [TrueForge](https://trueforge.dev), TrueFoundry's agent runtime.

---

## The problem it solves

Triaging a suspected phishing or business-email-compromise message is slow, and the useful
response actions (quarantining mail, emailing a real person to warn them, filing an abuse
report) are the kind of thing you do **not** want an AI doing on its own. UNIVERSAL IMPORTS
splits the job: the agent does the fast evidence-gathering, and a person keeps a hand on the
trigger for every consequential step.

---

## How it works

1. **Parse the email** — headers, SPF/DKIM/DMARC results, links, attachment hashes. No
   internet access in this step.
2. **Three investigations run in parallel:**
   - **Infrastructure** — how old is the domain? how old is its TLS certificate? is the URL
     known-bad?
   - **Identity** — does the display name match the Reply-To / Return-Path? is the domain a
     look-alike of a real one?
   - **History** — have we ever received mail from this sender or domain before?
3. **"Detonate" the link** — follow the redirects and read the final page *as text* (no
   browser, no rendering), and flag any form that asks for a password.
4. **Write the verdict** — a short, plain-English judgement.
5. **Propose up to four actions**, each one held behind its own approval gate (see below).

---

## Safety: nothing irreversible happens without you

The four actions the agent can propose are all **gated**:

| # | Action | What it does |
|---|--------|--------------|
| 1 | `quarantine` | Tags the message so it's set aside |
| 2 | `notify_impersonated` | Emails the real person being impersonated to warn them |
| 3 | `create_block_rule` | Records a "block mail like this" decision |
| 4 | `file_abuse_report` | Emails an abuse report to the domain's registrar |

When the agent tries to run one of these, **TrueForge pauses, shows you the exact request,
and waits for you to click Allow or Deny.** A denied action does not run, and the agent is
told not to try to reach the same outcome another way. The gates are enforced by the
platform, not by the agent's own good behaviour.

---

## Try it in 2 minutes (no accounts, no keys, no Docker)

You can explore the whole workflow in the browser with sample data before setting anything
else up.

**You need:** [Node.js](https://nodejs.org) version 22 or newer.

```bash
cd cockpit
npm install
npm run dev
```

Open the URL it prints (usually `http://localhost:5173`). You'll see a complete sample
mission play out: the parsed message, the three evidence lanes, the detonation result, the
verdict, and the four **LICENCE REQUIRED** gates. This runs entirely offline from a bundled
fixture — no live agent is involved yet.

---

## Run the real agent

This connects the agent to a live model and lets it actually investigate an email and ask
you to approve actions.

### What you need first

- **[Docker](https://www.docker.com/)** — for the local mail server and test portal.
- **[Python](https://www.python.org/) 3.11 or newer** — for the tools service.
- **[Node.js](https://nodejs.org) 22 or newer** — for TrueForge and the UI.
- **TrueForge** — no install needed; it runs via `npx`.
  **On Windows, run TrueForge from inside WSL2 (Ubuntu).** It crashes on native Windows.
  Ideally run the whole project from WSL2's own filesystem, not a Windows-mounted folder.
- **On Linux or WSL2 only:** the packages `bubblewrap`, `socat`, and `ripgrep`
  (`sudo apt-get install -y bubblewrap socat ripgrep`). The agent config turns on TrueForge's
  built-in **local sandbox**, and TrueForge needs those three commands to start it. This is
  *not* Daytona and needs no account or credential — but without the packages, registering
  the agent fails with a misleading "no sandbox provider is configured" error.
- **Your own model-provider API key** — see the next box.

> ### ⚠️ You must bring your own model-provider API key
>
> This project does **not** come with an API key, and there is no shared key from another
> developer. You need your own key from a model provider — for example an **Anthropic API
> key** ([console.anthropic.com](https://console.anthropic.com/)).
>
> You enter the key **in TrueForge's settings screen in your browser** (Step 5 below). It is
> never typed into this repository, committed, or stored in any project file.
>
> **You are responsible for your own provider usage and any costs it incurs.** Set a spend
> limit in TrueForge's settings, and in your provider's dashboard, before running the agent.

### Steps

Run each numbered block from the **repo root**.

**1. Start the local mail server and test portal.**

```bash
cd range
docker compose up -d
bash seed.sh          # Windows PowerShell: ./seed.ps1
cd ..
```

This starts [Mailpit](https://mailpit.axllent.org/) (a fake inbox) at `http://localhost:8025`
and a fictional phishing portal at `http://localhost:8080`, then loads 20 sample emails into
Mailpit. If `seed.sh` fails because Mailpit isn't ready yet, wait a few seconds and run it
again.

**2. Set up the tools service.**

```bash
cd tools
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd ..
cp .env.example .env           # optional — every value defaults to the local mail server
```

You only need to edit `.env` if you have a [URLhaus](https://urlhaus.abuse.ch/) API key
(optional; it's a weak signal) or want to point the tools somewhere other than the local
Range.

**3. Start the tools service.** Leave this running in its own terminal.

```bash
cd tools
.venv/bin/python -m imports_mcp.server    # Windows: .venv\Scripts\python -m imports_mcp.server
```

It serves the agent's tools at `http://localhost:8941/mcp`.

**4. Start TrueForge.** Leave this running in its own terminal. On Windows, run it from WSL2.

```bash
npx @truefoundry/trueforge     # serves at http://localhost:8790
```

**5. Add your own model-provider API key.** Open `http://localhost:8790` in your browser and
go to its settings. Add a model provider (e.g. Anthropic), paste in **your own** API key, and
set a spend limit. Make sure the model named in `harness/agent.json` (currently
`anthropic/claude-sonnet-5`) is available from your provider — or change that line in
`harness/agent.json` to a model you have access to.

**6. Register the agent and connect its tools.** You can add the tools connector in
TrueForge's settings (a "remote" MCP server named `imports-mcp` at the URL
`http://localhost:8941/mcp`). Or do both from the command line:

```bash
# connect the tools service
curl -X POST http://localhost:8790/api/v1/settings/mcp-servers \
  -H "Content-Type: application/json" \
  -d '{"manifest":{"type":"remote","name":"imports-mcp","url":"http://localhost:8941/mcp","description":"Universal Imports tools"}}'

# register the agent
curl -X POST http://localhost:8790/api/v1/agents \
  -H "Content-Type: application/json" \
  -d @harness/agent.json
```

**7. Open the UI, pointed at the live agent.**

```bash
cd cockpit
npm install
VITE_TRUEFORGE_URL=http://localhost:8790/api/v1 \
VITE_TRUEFORGE_INPUT="A suspicious email has been saved as the fixture 01-credential-phish.eml. Call parse_message with that exact filename to begin your analysis." \
npm run dev
```

`VITE_TRUEFORGE_INPUT` is the agent's opening instruction. It must name one of the sample
email files in `tools/fixtures/` — `01-credential-phish.eml`, `02-invoice-fraud-bec.eml`, or
`03-legitimate.eml` — because the agent's first step is to call `parse_message` with that
filename. The UI's status line will read **live TrueForge** instead of **fixture playback**.
Reload the page to start a run; approve or deny each gate as it appears.

### Check that it's working

- **TrueForge sees the agent:** `curl http://localhost:8790/api/v1/agents` lists
  `universal-imports`.
- **TrueForge sees the tools:** `curl http://localhost:8790/api/v1/mcp-servers/imports-mcp/tools`
  lists `parse_message`, `domain_intel`, `url_reputation`, `correspondence_history`,
  `detonate`, and the four gated actions.
- **The code passes its own tests** (see [Developer / Advanced](#developer--advanced)).

---

## Architecture

```
  a saved .eml file, passed to parse_message
        │
   ┌────▼──────────────────────────────────────────┐
   │ NORMALISE — RFC822 parse, no network          │
   │ headers · SPF/DKIM/DMARC · URLs · attachments │
   └────┬──────────────────────────────────────────┘
        │  TrueForge lead agent
   ┌────▼───────────┬────────────────┬─────────────┐
   │ INFRASTRUCTURE │   IDENTITY     │   HISTORY   │  ← 3 subagents, requested in parallel
   │ RDAP age       │ display-name   │ prior mail  │
   │ cert age       │  vs reply-to   │ from this   │
   │ URLhaus        │ lookalike dom. │ person/dom. │
   │ + DETONATION ──┤                │             │
   └────┬───────────┴────────────────┴─────────────┘
        │
   ┌────▼──────── DETONATION (text-mode) ──────────┐
   │ redirect chain · HTML parse · form targets ·  │
   │ asks-for-password? — no browser, no screenshot│
   └────┬──────────────────────────────────────────┘
        │
   ┌────▼──────────────────────────────────────────┐
   │ VERDICT + EVIDENCE  →  up to 4 PROPOSED ACTIONS│
   └────┬──────────────────────────────────────────┘
        │
   ┌────▼── 🔶 FOUR SEQUENTIAL LICENCE GATES ──────┐
   │ TrueForge pauses on each approval-marked tool │
   │ call and shows the exact request.             │
   │  1. quarantine          → [Allow] [Deny]      │
   │  2. notify_impersonated → [Allow] [Deny]      │
   │  3. create_block_rule   → [Allow] [Deny]      │
   │  4. file_abuse_report   → [Allow] [Deny]      │
   └────┬──────────────────────────────────────────┘
        │
   execute the approved actions · speak the verdict
```

### What's real today, and what is the design target

- **Detonation is text-mode only.** It follows redirects and parses the final page's HTML;
  it does **not** open a browser or take a screenshot. A sandboxed headless-browser version
  with a real screenshot is the design goal, not something that exists yet.
- **There is no mailbox connection.** The agent does not watch a real inbox. You feed it a
  saved `.eml` file from `tools/fixtures/`. Everything from parsing onward is real.
- **All four gated tools exist and are tested.** `quarantine`, `notify_impersonated`, and
  `file_abuse_report` act against the local mail server. `create_block_rule` records the
  decision durably, but nothing in the project reads block rules back yet — no mail is
  actually blocked.
- **The three subagents are a request, not a guarantee.** `harness/agent.json` asks the
  model to split the work into Infrastructure / Identity / History; TrueForge decides at
  runtime how it actually delegates.

---

## Repo layout

```
/contracts   Shared TypeScript types + the sample mission the UI plays back offline.
/harness     TrueForge configuration (agent.json), the turn-stream translator, and the
             text-mode detonation logic.
/tools       The "imports-mcp" tools service: email parser, intel lookups
             (RDAP / crt.sh / URLhaus), correspondence history, detonation, and the four
             gated actions.
/cockpit     The UI — a Vite + React app that shows a mission as it happens.
/mission     The agent's skills, the evaluation harness, and its research-corpus fixtures.
/range       Docker Compose for Mailpit (mail capture), the fake phishing portal, and the
             20 sample emails that get seeded into Mailpit.
PLAN.md      The full plan, task board, decisions, and history — read this for "why".
CLAUDE.md    The working rules this project holds itself to.
```

---

## Safety rules

- The sandbox holds no credentials and has no route back to real infrastructure.
- Remote images in emails are never rendered (a loaded tracking pixel confirms a live address).
- Attachments are hashed (SHA-256) and never opened or executed.
- Sample emails use only invented brands ("Northgate Trust", "Meridian Courier"), never a
  real company. The 20 emails seeded into the local mail server link only to the local test
  portal.
- `detonate` follows the links it is given. It refuses private and loopback addresses (unless
  a test-only flag is set), but it will make a real request — capped at 5 seconds and 10
  redirects — to a public address. One of the three starter files, `01-credential-phish.eml`,
  points at an external IP for this reason.
- The gated actions refuse to reach outside the local Range by default. In particular,
  `file_abuse_report` will not email a real registrar unless you deliberately opt in.
- Every one of the four consequential actions stops for an explicit human Allow/Deny before
  it can run.

---

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

---

## Developer / Advanced

### Run the test suites

```bash
# Python tools (from the repo root, with tools/.venv active):
pytest

# Harness:
cd harness && npm install && npm test && cd ..

# UI (type-check + build):
cd cockpit && npm install && npm run build && cd ..
```

Live-network tests are opt-in only (`RUN_LIVE_*` environment variables) and never run in a
normal `pytest` / `npm test`.

### The UI's two modes

`cockpit` plays back the bundled fixture (`contracts/fixtures/mission-happy-path.json`) by
default, so it works with nothing else running. Setting `VITE_TRUEFORGE_URL` and
`VITE_TRUEFORGE_INPUT` (Step 7 above) switches it to a live TrueForge run. See
`cockpit/README.md`.

### Evaluation harness

`mission/eval/` scores the agent against 40 real research-corpus emails (20 phishing, 20
legitimate) on how often it correctly proposes a gated action. It needs the live stack from
"Run the real agent" above. See `mission/eval/README.md`.

### The sandboxed-browser / Daytona path

The design target for detonation is a headless browser running in a remote Daytona sandbox,
producing a real screenshot. It is not built: no Daytona account is configured, and the
"second run must be fast" requirement needs a snapshot mechanism TrueForge doesn't expose.
(Note: the Range's seeded emails link to the local test portal on `localhost`, and
`detonate`'s guard refuses loopback addresses unless the test-only flag is set — so those
particular links are not followed by a normal run.) See `PLAN.md` §5.

### More detail

- `harness/README.md` — TrueForge configuration, the turn-stream translator, the Windows/WSL2
  crash and workaround.
- `mission/eval/README.md` — how the evaluation harness measures accuracy without inventing a
  verdict label.
- `PLAN.md` — the full task history and every design decision, with reasons.
