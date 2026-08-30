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
