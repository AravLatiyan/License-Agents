# UNIVERSAL IMPORTS

An email counter-intelligence agent. Forward it anything asking you to click, pay, reset, or
approve. It detonates the payload in a sandbox, sends three subagents after who's really behind
it, and comes back with a verdict and a set of proposed actions — **none of which happen until a
human grants the licence for each one.**

Built on [TrueForge](https://trueforge.dev), TrueFoundry's agent runtime. See `PLAN.md` for the
full plan, decisions, and task history, and `CLAUDE.md` for the project's working rules.

## Architecture

```
  message arrives (IMAP / maildir watch)
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
   ┌────▼────────── DAYTONA SANDBOX ───────────────┐
   │ fake portal on sandbox localhost (Range mode) │
   │ headless chromium · redirect chain            │
   │ screenshot · form targets · asks for password?│
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

**The Daytona sandbox catch:** Daytona is remote and cannot reach a Range running on your
laptop's `localhost`. The fake portal runs *inside the sandbox itself* instead — zero
networking, works offline, works on a judge's machine.

## Repo layout

```
/contracts     shared TypeScript types + fixture event stream (Owner 1/2/3 shared)
/harness       TrueForge config (agent.json), the turn-stream → mission.* translator,
               text-mode detonation
/tools         the imports-mcp MCP server: normaliser, intel APIs (RDAP/crt.sh/URLhaus),
               correspondence history, detonation, the four gated actions
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

**1. Bring up the Range** — a real, self-contained mailbox + a fictional phishing portal, so the
demo runs entirely offline on your own machine (rule 5: a judge should be able to clone this and
watch it work without trusting a video):

```bash
cd range
docker compose up -d
bash seed.sh   # or seed.ps1 on Windows — posts the 20 fixtures into Mailpit
```

Mailpit's UI is now at `localhost:8025`; the fake portal listens on `localhost:8080` (only
reachable from inside a sandbox in the real flow — see the Daytona note above).

**2. Set up `tools/` (the MCP server)**

```bash
cd tools
python -m venv .venv
.venv/Scripts/activate        # .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp ../.env.example ../.env    # fill in URLHAUS_AUTH_KEY if you have one; everything else
                               # defaults to the local Range
```

Run its test suite from the repo root (the root `pytest.ini` wires `tools/` onto
`PYTHONPATH`):

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
```

**4. Run the Cockpit UI**

```bash
cd cockpit
npm install
npm run dev
```

By default it plays back a static fixture (`contracts/fixtures/mission-happy-path.json`) so the
UI is fully explorable without a live TrueForge connection.

## Safety rules

- The sandbox holds no credentials and has no route back to real infrastructure.
- Remote images are never rendered (tracking-pixel confirmation risk).
- Attachments are hashed and looked up — never executed.
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
