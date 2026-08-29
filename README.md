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
   │  3. block rule        → [Allow] [Deny]  (not built — see note below) │
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
- **The third licence gate, `create_block_rule`, doesn't exist yet.** It's configured as a gate
  name in `harness/agent.json` so the *shape* of "four sequential gates" is correct, but no tool
  implements it and nothing would consume a block rule if it did — see `PLAN.md` §5 (T-032). The
  other three gates (`quarantine`, `notify_impersonated`, `file_abuse_report`) are real, tested
  tools.

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
               correspondence history, detonation, and three of the four gated actions
               (quarantine, notify_impersonated, file_abuse_report — create_block_rule is
               configured as a gate but not yet implemented, see the note above)
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

## More detail

- `harness/README.md` — TrueForge config, the turn-stream translator, known Windows/WSL2 issues.
- `mission/eval/README.md` — the gate-trigger evaluation harness (T-042): how it measures
  accuracy without inventing a verdict classifier, and how to run it against a live agent.
- `PLAN.md` — everything else: the full task history, every design decision and why, and the
  demo script this project is built against.
