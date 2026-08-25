# UNIVERSAL IMPORTS — PLAN & LIVE STATUS
> **Nothing gets in without clearance.**
> The Agent Harness Hackathon · WeMakeDevs × TrueFoundry × Qodo · 24–30 Aug 2026
> **Deadline: 30 Aug 20:00 London = 31 Aug 00:30 IST. We submit 30 Aug, 18:00 IST.**

**This is the only planning file. Everything lives here: the plan, the task board, progress,
decisions, errors, and the traps. Claude Code reads and updates it every session.**

---

# ⚡ HOW THIS FILE WORKS

1. **§1 LIVE STATUS** is the top of every session. Claude reads it first and reports it back.
2. **§2 NEXT UP** always holds **exactly 4 tasks**. Claude presents them as a numbered menu and
   waits for you to pick one. Never more than one at a time.
3. When a task finishes: Claude moves it to **§4 DONE** with a result line, deletes it from
   NEXT UP, pulls replacements from **§11 BACKLOG**, and shows the new menu.
4. Anything learned goes into **§5 BLOCKED**, **§6 DECISIONS**, or **§7 ERRORS** as it happens —
   never batched for later.
5. If the plan turns out to be wrong, it goes in **§8 SUGGESTED CHANGES**, gets raised at
   standup, and someone edits the plan sections below. **The plan is allowed to change; drifting
   silently is not.**

Sections §1–§8 are living. Sections §9–§18 are the reference and change only by decision.

---

# §1 LIVE STATUS

```
PHASE:        DAY 1 — SLICE 1 (ugly vertical slice)
DATE:         2026-08-25
DAYS LEFT:    5
ACTIVE:       Owner 1 (Harness) · Owner 2 (Tools)
DORMANT:      Owner 3 (Cockpit) · Owner 4 (Mission)
TODAY'S GOAL: Slice 1 running end to end, ugly (O1). imports-mcp skeleton + parse_message done, domain_intel next (O2).
BLOCKED ON:   nothing
LAST UPDATED: 2026-08-26 09:18 · PR #1, #2, #3 merged (T-013/T-017/T-002/T-014+Qodo-fixes all on main); T-003, T-004, T-010, T-011, T-012 done (O2)
```

## 🚨 DO THIS FIRST — before any task below
- [ ] Repo **public** on GitHub, MIT licence
- [ ] **Qodo installed on the repo** — `app.qodo.ai/signin` → link GitHub → install on this repo.
      **Before the first real commit.** ~10 minutes, then zero ongoing effort. See §15a for why
- [ ] `main` protected: require a PR, require one review
- [ ] Everyone **registered** for the hackathon (free, one form)
- [ ] Everyone **starred `github.com/truefoundry/trueforge`** (free prize draw)
- [x] `node --version` ≥ 22 · `npx @truefoundry/trueforge` → `localhost:8790` — **on Windows, run this from WSL2 with Node installed inside the distro, not native Windows (segfaults). See §7**
- [ ] Model provider configured · **hard spend cap set on the API key**
- [ ] Everyone has opened **at least one PR today**

---

# §2 NEXT UP — PICK ONE

> Claude: present these as a numbered menu, wait for a choice, then work only on that one.

| # | ID | Task | Owner | Size | Why now |
|---|---|---|---|---|---|
| 1 | **T-015** | One approval gate wired end to end, action behind it may be a stub | O1 | — | Natural next step once T-002 answers how the gate surfaces over the API |
| 2 | **T-016** | `contracts/events.ts` + `contracts/fixtures/mission-happy-path.json` | O1+O2 | — | Contracts unblock O3/O4 the moment they join |
| 3 | **T-021** | `url_reputation` — URLhaus, as a third `imports-mcp` tool | O2 | | Auth-Key already confirmed live in T-003; same pattern as T-020 |

⏱ = has a timebox. See §3.

---

# §3 IN PROGRESS

> One row per active owner. Claude fills `Started` from `date` and checks elapsed time
> every few turns.

| ID | Owner | Started (IST) | Timebox | Fallback if it expires |
|---|---|---|---|---|
| T-020 | O2 | 2026-08-25 19:11 | 2h | Cache crt.sh hard; treat missing RDAP fields as "not published" rather than an error (§3's standing rule for intel APIs) |

### Timebox rules — Claude enforces these, not you
| Task | Box | Fallback |
|---|---|---|
| T-001 chromium in Daytona | **3h** | **Text-mode detonation** — HTTP redirect chain, HTML parse, form-target extraction, "this page asks for a password and posts it to a different domain." Still genuine sandboxed work. Screenshot becomes a stretch goal |
| T-002 approvals over the API | **2h** | Cockpit renders everything else (evidence lanes, detonation, verdict); the approval moment is filmed in TrueForge's own chat UI. Ugly for the UI track — try hard before accepting this |
| T-003 intel APIs | **2h** | Cache crt.sh hard; treat missing RDAP fields as *"not published"* rather than an error |
| Any single bug | **90 min** | Stub it, log it in §7, move on, return later |

**Do not negotiate with a timebox.** You agreed to these while calm. Every hour this project
loses will be lost to refusing a fallback, not to the work being too hard.

---

# §4 DONE

> Append-only. Format: `YYYY-MM-DD · T-XXX · [Owner] · what shipped — result`

2026-08-25 · T-013 · [O1] · `harness/agent.json` + `harness/README.md` — manifest for `POST /api/v1/agents` (model, instructions, sandbox+dynamic-subagents config), schema verified against trueforge.dev docs. `mcp_servers` left empty, `imports-mcp` not built yet (T-012) — result: written, not yet runtime-verified against a live server (see §7, Windows segfault)
2026-08-25 · T-017 · [O1] · Node installed inside WSL2 Ubuntu (NodeSource 22.x); TrueForge runs clean from there, no segfault, `curl` got HTTP 200 — result: `harness/agent.json` POSTed to the live `/api/v1/agents`, schema fully accepted, only rejection was the documented 422 "model provider not configured" (expected on a fresh instance, separate checklist item). T-013 now counts as runtime-verified. T-002 unblocked
2026-08-25 · T-002 · [O1] · **SPIKE 2 answered: YES, the HTTP API fully surfaces approvals — no chat UI needed.** Confirmed straight from the live server's own OpenAPI schema (not just docs): `POST /sessions/{id}/turns` streams SSE `TurnStreamingEvent`s; a gated tool call emits `tool.approval_required` (`type, id, created_at, thread_id, tool_calls[]`). Cockpit resumes by posting a turn with `input: [{type:"user.tool_approval", thread_id, tool_call_id, approval:{status:"allow"|"deny", reason?}}]`. `/turns/{id}/subscribe?after_sequence_number=` gives resumable SSE for free (reconnect handling, §10). Full details in §6 — result: cockpit's core interaction is fully buildable, T-036 unblocked
2026-08-25 · T-014 · [O1] · `harness/detonate.js` — text-mode detonation: follows redirects (manual, capped at 10 hops, non-http(s) schemes refused), parses final HTML with `node-html-parser` (never regex, per §12), flags forms that ask for a password and post cross-domain. Self-tested against a local-only fixture server (`harness/detonate.test.js`, `node --test`, 3/3 pass) — never touched a real domain (§13). `harness/package.json` added (one dependency: `node-html-parser`); root `.gitignore` added (`node_modules/` wasn't excluded before) — result: returns `{url, redirect_chain, final_url, forms, summary}`, matches §10's `detonate(url)` shape minus the screenshot field
2026-08-25 · T-014 (Qodo pass) · [O1] · Fixed 5 real bugs Qodo's PR #3 review found: fetch/DNS/timeout/malformed-redirect failures now return `{url, redirect_chain, error}` instead of throwing; one malformed form `action` no longer aborts analysis of the rest of the page (represented with `action_invalid: true` instead); HTML content-type check is case-insensitive; response body is read with a hard byte cap (`readBodyWithLimit`, streamed, never fully buffered) before parsing; non-HTML success responses now return the full documented shape including `summary`. 10/10 tests pass (7 new regression tests added). Declined one finding — see §8
2026-08-25 · T-003 · [O2] SPIKE 3 — all three intel sources confirmed live: RDAP via `rdap.org/domain/{domain}` (follow redirects) returns registration date + abuse contact; crt.sh reachable but 502ing on every attempt right now (matches known trap, mitigation unchanged); URLhaus `/v1/host/` and `/v1/urls/recent/` both confirmed working with the `Auth-Key` header already present in `.env` — added `.env.example` since none existed
2026-08-25 · T-004 · [O2] Read `bring-your-own-mcp` cookbook example (README, agent.json, mcp-server.mjs, package.json) end to end — settles trap #1 (transport mismatch) before any MCP code gets written
2026-08-25 · T-010 · [O2] Normaliser (`tools/imports_mcp/normaliser.py`) — RFC822 parse via stdlib `email`, URLs via `lxml.html` (href + anchor text, plain-text bare-URL fallback), attachment SHA256, raw Authentication-Results/Received chains passed through unverified. Smoke-tested against a synthetic phish + a synthetic legit mail, both correct
2026-08-25 · T-011 · [O2] 3 fixtures in `tools/fixtures/` — credential phish (SPF/DKIM/DMARC fail, raw-IP href vs polished anchor text), invoice fraud/BEC (homograph lookalike domain `universaI-imports.co` where auth actually PASSES, reply-to redirected to a third domain, PDF attachment), and one legitimate mail that must not trip anything. All hand-written `Authentication-Results`/`Received` headers per trap #11. Ran the T-010 normaliser against all three — every signal (auth fail, href/anchor mismatch, reply-to mismatch, attachment hash) came through correctly
2026-08-25 · T-012 · [O2] `imports-mcp` skeleton (`tools/imports_mcp/server.py`) — one tool, `parse_message(fixture)`, wired to the T-010 normaliser against the T-011 fixtures. Streamable HTTP per T-004, whitelisted fixture lookup (rejects unknown names and path traversal via `ToolError`, not a bare exception). 11 tests: 9 contract-level (direct function calls, no server) + 2 real end-to-end over the actual HTTP transport with the official MCP client — all pass

---

# §5 BLOCKED

| ID | Owner | Blocked on | Since | Who can unblock |
|---|---|---|---|---|
| _(nothing)_ | | | | |

---

# §6 DECISIONS

> One line each, dated, **with the reason**. Logged the moment a decision is made, never batched.
> Any argument running past 10 minutes goes to Owner 4, gets one line here, everyone moves on.

```
2026-08-24 · [all] · Project is UNIVERSAL IMPORTS — email counter-intelligence — the sandbox is genuinely load-bearing, there are four natural approval gates, and no other team wires both sponsors together
2026-08-24 · [all] · Fake portal runs INSIDE the Daytona sandbox — Daytona is remote and cannot reach localhost on our laptops
2026-08-24 · [all] · IMAP + app password, never the Gmail API — gmail.modify is a restricted scope costing a day in consent screens and review
2026-08-24 · [all] · Read the Authentication-Results header, never verify DKIM ourselves — DNS + canonicalisation is a two-day rabbit hole
2026-08-24 · [all] · PhishTank excluded — registration closed since 2020, still closed in 2026
2026-08-24 · [all] · URLhaus is one weak signal only — it is malware-focused, not phishing-focused, so "not listed" does not mean safe
2026-08-24 · [all] · Demo script (§17) written before the code — any feature that can't name its second in the video doesn't get built
2026-08-24 · [all] · Approval gates are FOUR SEQUENTIAL per-tool-call gates, not one modal with four checkboxes — TrueForge's native approval is per tool call, boolean, and shows the JSON request. We configure it in agent.json, we do not build it. Four stopping moments is also more cinematic than one modal
2026-08-24 · [all] · Sandbox lifecycle is TrueForge's job, not ours — we only write what runs inside it. Spike 1 must measure SECOND-RUN time, not just whether chromium installs: a 4-min install that works in testing dies on camera
2026-08-24 · [all] · Qodo installed and left alone — it is half of judging criterion 04 which is scored on EVERY submission regardless of track. 10 min setup, zero ongoing. We are NOT chasing the Best Code Quality track itself; four iPads on Best UI beats one Mac Mini split four ways
2026-08-25 · [O1] · Detonation defaults to TEXT-MODE FALLBACK (HTTP redirect chain, HTML parse, form-target extraction) — Spike 1 (chromium in Daytona) never produced committed work inside its 3h box, box expired ~9h unattended. Screenshot detonation is now a stretch goal only, revisited if Slice 1–3 land early
2026-08-25 · [O1] · Cockpit (O3) builds against the HTTP/SSE API directly, never the chat UI — POST /sessions, POST /sessions/{id}/turns (stream:true → SSE), watch for `tool.approval_required` events, resume with a turn whose input is `{type:"user.tool_approval", thread_id, tool_call_id, approval:{status:"allow"|"deny"}}`. Reconnects use GET /turns/{id}/subscribe?after_sequence_number=. Confirmed against the live server's own OpenAPI schema, not just docs (T-002)
2026-08-25 · [O2] · RDAP lookups go through `rdap.org/domain/{domain}` with redirects followed, not hardcoded per-registry servers — one entry point, confirmed fast (~0.5s) and correct
2026-08-25 · [O2] · URLhaus now requires the `Auth-Key` header on every endpoint, including read-only host/url lookups, not just submissions — code the intel client assuming auth is mandatory everywhere
2026-08-25 · [O2] · `imports-mcp` is Streamable HTTP via the official **Python** MCP SDK's `MCPServer` — **not** Express/JS. The `bring-your-own-mcp` cookbook (which is Node/Express) only settled the transport *shape* (Streamable HTTP, not stdio); the language/SDK is Python per the decision directly below, since `/tools` is Python. Registered in TrueForge via Settings → Connectors then referenced by name in `agent.json`
2026-08-25 · [O2] · `imports-mcp` runs `stateless_http=True` **with `json_response=True`** — the default SSE response mode hung forever on a tool error under statelessness (see §7). Every future tool in this server inherits this config, don't change it without re-testing the error path
2026-08-25 · [O2] · Raise `mcp.server.mcpserver.exceptions.ToolError` for anticipated tool failures, not a bare exception — a bare exception gets wrapped into a generic "Error executing tool X" and the real reason never reaches the model; `ToolError` preserves the message and skips the noisy traceback log
2026-08-25 · [O2] · `/tools` is Python — stdlib `email` for RFC822 parsing, `lxml` for HTML (per the trap in §12), MCP server on the official Python MCP SDK's streamable-HTTP transport to match T-004's findings
```

---

# §7 ERRORS / SURPRISES

> Anything that cost someone time, so nobody pays it twice.

| Date | Owner | What bit us | What to do instead |
|---|---|---|---|
| 2026-08-25 | O1 | T-001 picked, timeboxed, session ended with no commit — nothing landed in git, no files, no findings. ~9h lost to Day 0 gate before anyone noticed the box had expired | Commit as you go, not just at task end. If a session might end mid-task, commit a WIP note to PLAN.md §3 at minimum so the next session can see real elapsed state, not just a stale timestamp |
| 2026-08-25 | O1 | `npx @truefoundry/trueforge` **segfaults on native Windows**, reproduced twice, right after it logs `Local sandbox fallback is unavailable (win32 not supported)`. Running it from WSL2 without Node installed *inside* the Linux distro just falls through to the Windows node.exe via interop — same crash | Whoever is on Windows: install Node inside WSL2 Ubuntu itself (`curl -fsSL https://deb.nodesource.com/setup_22.x \| sudo -E bash - && sudo apt-get install -y nodejs`, or nvm) and run TrueForge from there, not from Windows or from WSL-with-Windows-node. **Fixed — T-017 done, confirmed working** |
| 2026-08-25 | O1 | Driving `wsl.exe` from this Bash tool (which is Git Bash/MSYS) silently mangled `/mnt/c/...` paths — MSYS rewrites leading `/` args before handing them to native exes, turning `/mnt/c/...` into `C:/Program Files/Git/mnt/c/...`. Also: separate `wsl -d Ubuntu -- bash -lc "..."` calls don't share state — WSL2 tears the instance down ~8s after the last process exits, killing anything backgrounded with plain `&`/`nohup` between calls | Prefix the command with `MSYS_NO_PATHCONV=1` to stop the path rewrite. Do the whole start-and-poll-and-verify sequence in **one** `wsl` invocation (one script), not several — that's also what actually needs `setsid ... </dev/null` to background cleanly within that one call |
| 2026-08-25 | O1 | `harness/README.md` fell out of date **within the same PR** — T-017 fixed the Windows segfault and runtime-verified `agent.json`, but the README's "known issue" section still read as unresolved. Qodo's first-pass review caught it (2 Medium findings) rather than us | When a task's result changes something already documented elsewhere in the same branch, update that doc in the *same commit* as the fix, don't leave stale wording for review to catch |
| 2026-08-25 | O2 | crt.sh returned 502 on 7/7 live attempts against two different domains, in-line with the known trap | Ship the 5s timeout + SQLite cache from day one (T-045) — don't wait for it to fail in front of a judge |
| 2026-08-25 | O2 | No `.env.example` existed even though a real `.env` with `URLHAUS_AUTH_KEY` was already in the repo (gitignored, untracked — never committed) | Added `.env.example` with the key name and no value; do this for every new secret going forward |
| 2026-08-25 | O2 | `imports-mcp` server hung forever (never returned, client never timed out) on the very first error-path tool call — `stateless_http=True` combined with the default SSE response mode (`json_response=False`) apparently never closes the event stream when a tool raises. Cost ~15 min to bisect with a background process + hard-timeout client before finding it | Pass `json_response=True` alongside `stateless_http=True` for any single-purpose stateless MCP tool server — plain JSON responses, no SSE needed for a request that's just "call one tool, get one answer" |
| 2026-08-25 | O2 | `python` on PATH in Git Bash resolves to an MSYS2 build (`C:\msys64\ucrt64\bin\python.exe`) with no PyPI wheels for compiled packages — `pip install lxml` tried to compile from source and failed on a missing `libxml/xpath.h` | Use the python.org install instead (`py -3` or the full path under `AppData\Local\Programs\Python\`) when creating `tools/.venv` — every O2 teammate on Windows needs to know this |

---

# §8 SUGGESTED CHANGES TO PLAN

> The plan is wrong sometimes. Write it here, raise it at standup, then edit the sections below.

| Date | Owner | Suggestion | Status |
|---|---|---|---|
| 2026-08-25 | O1 | Plan assumed `harness/agent.json` is a file TrueForge itself reads. It isn't — agents are created via `POST /api/v1/agents` with a `manifest` body (model, instructions, mcp_servers incl. `require_approval_for_tools`, config). We're keeping `agent.json` as our repo-committed source of truth for that manifest and seeding it with a `curl` POST — matches the spirit of "configuration, not code" (§10) just via API instead of a config file TrueForge auto-loads | Adopted, see `harness/README.md` |
| 2026-08-25 | O1 | Qodo's PR #3 review flagged `detonate.test.js`'s fixture server for using `127.0.0.1` as a rule violation, citing the "Daytona can't reach localhost" trap. **Declined, on reconsideration with fuller evidence.** The only documented rule (CLAUDE.md #9, PLAN.md §12, both verbatim-checked) says the *production fake portal* must live inside Daytona because a remote sandbox can't dial back to a laptop — a network-reachability fact about one specific target, not a blanket ban on localhost. Neither file mentions test fixtures. Implementing Qodo's literal remediation (host the test fixture inside a live Daytona sandbox) would need Daytona credentials we don't have, spin a sandbox per test run (directly violating CLAUDE.md trap #4: "never spin a fresh sandbox per detonation"), and break a judge's clean-clone test run (rule 5, T-065) — trading one claimed violation for three real ones. **What Qodo did get right, and what we missed the first pass:** §10's architecture diagram draws detonation (redirect chain, form targets — exactly what `detonate.js` does) as running *inside* Daytona in the intended production pipeline, and T-014's own backlog line calls the text-mode fallback "still genuine sandboxed work." So production `detonate.js` genuinely is meant to eventually execute inside a Daytona sandbox — that wiring doesn't exist yet (T-035, scope clarified below). That's a real, separate gap from this test-fixture question, out of T-014's scope/timebox as built. Replied on the Qodo thread with this full reasoning | Declined, reasoning posted on PR #3's review thread; T-035 scope clarified |
| 2026-08-25 | O1 | **The exact conflict on finding #3 (Qodo Rule 2880752), stated precisely.** Rule 2880752 ("Disallow running the detonation fake portal on localhost," `app.qodo.ai/rules/2880752`) is a *standing, account-level Qodo Compliance Rule* — not a per-review inference. It reads: "detonation-related fixtures are required to run at a Daytona sandbox endpoint," with no carve-out for test-only fixtures. This is broader than its source text (CLAUDE.md #9 / PLAN.md §12), which names one specific case: the *production* fake portal must be reachable *by a real, remote Daytona sandbox*, because Daytona can't dial back to a laptop. `detonate.test.js`'s fixture triggers neither the wording's condition nor its reason — the code under test (`detonate.js`) has no Daytona integration (§11 T-035, unbuilt) and isn't invoked from inside any sandbox in this test; both the fetcher and the fixture run in the same local Node process, so there is no remote-sandbox-to-laptop gap to cross. The conflict is therefore rule-scope vs. architecture, not evidence vs. architecture: satisfying the rule as written would mean building Daytona orchestration as a prerequisite for a task explicitly scoped as the fallback *because* that spike didn't land, and would itself break CLAUDE.md trap #4 and rule 5/T-065 (§8, row above). Rule stays as configured — no repo-level Qodo config exists to change (checked: no `.qodo*`/`pr_agent*` file in the repo; the rule lives entirely on the Qodo dashboard) — and no change was made to it. Declined via a `@qodo dismiss` reply on the finding's thread instead, since that records the decision on the PR without touching rule configuration | Declined; dismissal requested on PR #3, rule config untouched (needs explicit approval to change) |
| 2026-08-25 | O1 | Whoever's on Windows for real dev work should expect to run TrueForge from WSL2 (with Node installed inside the distro), not native Windows — it segfaults there. Worth a line in the top-level README's setup steps once written (T-065 checks this on clean clone) | Open |

---
---

# §9 THE PROJECT

> Forward it anything asking you to click, pay, reset, or approve. It detonates the payload in a
> sandbox, sends three operatives after who's really behind it, and comes back with a verdict and
> a set of actions — **none of which happen until you grant the licence.**

**Codename:** UNIVERSAL IMPORTS — counter to their "Universal Exports" track. Bond's cover was an
import/export firm; counter-intelligence is the half nobody names.

## Why it qualifies (rule 3 + best practice 01)
A judge must see the harness **reach a tool, run code in the sandbox, and stop for a person.**
Ours does all three inside 90 seconds:
- **Reaches:** IMAP mailbox, RDAP, crt.sh, URLhaus, our own MCP server
- **Runs code in the sandbox:** deliberately detonates a stranger's payload — the sandbox is the
  *point*, not a feature bolted on for the rubric. **Say this line in the voiceover**: their own
  ideas slide lists "untrusted code runner"; we want the judge to see *why* the sandbox exists,
  not just that it does
- **Stops for a person:** four irreversible actions, each individually gated

## Why it beats the alternatives
- *Incident responder* is flagged **HERO PROJECT** on their own site — most crowded lane, and the
  baseline version is literally their illustration handed back to them
- *Issue-to-PR* is a dev tool at a dev hackathon; there will be six
- Ours is the only one where the **sandbox is load-bearing** and the person who needs it most
  isn't a developer

## Judging map (six criteria, weighted equally)
| Criterion | How we score |
|---|---|
| Potential impact | Everyone has a parent who's been phished or a company that's lost money to invoice fraud |
| Creativity | Nobody at a dev hackathon builds counter-intelligence |
| Technical excellence | Six harness primitives used because the job needs them, plus a published eval number |
| Use of sponsor tools | TrueForge *is* the runtime; Qodo reviews every PR from day one |
| **Control and safety** | The whole product *is* a control-and-safety story |
| Presentation | Bond theme, amber cockpit, a literal LICENCE REQUIRED gate |

---

# §10 ARCHITECTURE

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
   │ call and shows the JSON request. We configure │
   │ this in agent.json — we do not build it.      │
   │  1. quarantine        → [Allow] [Deny]        │
   │  2. notify impersonated → [Allow] [Deny]      │
   │  3. block rule        → [Allow] [Deny]        │
   │  4. abuse report      → [Allow] [Deny]        │
   └────┬──────────────────────────────────────────┘
        │
   execute granted · write campaign dossier · speak the verdict
```

## 🔴 The architecture catch that would have cost us an afternoon
**Daytona is remote. It cannot reach a Range running on `localhost` on your laptop.**
→ The fake portal runs **inside the sandbox itself.** Zero networking, works offline, works on a
judge's machine, and it's more honest — payload and browser isolated together.

## Repo layout — you own a folder, full stop
```
/contracts     shared types + fixture event stream · PR needs 2 approvals
/harness       O1 — TrueForge config, agent.json, sandbox job, subagents
/tools         O2 — imports-mcp server, normaliser, intel APIs, gated actions
/cockpit       O3 — the UI
/mission       O4 — Range fixtures, skills, prompts, eval harness
PLAN.md        this file
CLAUDE.md      the rules Claude Code auto-reads
```

## MCP tool surface (`tools/imports-mcp`)
| Tool | Returns | Gated |
|---|---|---|
| `parse_message(id)` | headers, auth results, URLs, attachment hashes | no |
| `domain_intel(domain)` | RDAP age/registrar/abuse contact; crt.sh cert age | no |
| `url_reputation(url)` | URLhaus verdict + tags | no |
| `correspondence_history(address, domain)` | prior contact count, first/last seen, domains used | no |
| `detonate(url)` | redirect chain, screenshot ID, form analysis | no |
| `quarantine(message_ids)` | — | ⚠️ **yes** |
| `notify_impersonated(address, evidence)` | — | ⚠️ **yes** |
| `create_block_rule(pattern)` | — | ⚠️ **yes** |
| `file_abuse_report(domain, evidence)` | — | ⚠️ **yes** |

**Every tool response under ~2KB. Never return raw HTML to the model.**

## Owners
| | Role | Folder | Backup |
|---|---|---|---|
| **O1** | Harness — TrueForge config, agent.json, sandbox job, subagents, approvals, sessions | `/harness` | O2 |
| **O2** | Tools — MCP server, normaliser, intel APIs, the four gated actions | `/tools` | O1 |
| **O3** | Cockpit — the UI, **and the four iPads** | `/cockpit` | O4 |
| **O4** | Mission — Range, skills, prompts, evals, Qodo trail, README, video, blog. **Tiebreaker** | `/mission` | O3 |

---

# §11 BACKLOG — refill NEXT UP from here

> Claude pulls from the top of the current slice when a task completes. Move an item here to
> §2 rather than inventing a new one, unless §8 says the plan changed.

## Slice 1 — ugly vertical slice (Day 1)
*One hardcoded fixture → parse → one subagent → hardcoded verdict → one approval gate → cockpit shows it. It will be hideous. It must run before anyone sleeps.*
- **T-013** [O1] `harness/agent.json` — first saved agent: model + instructions + connectors

## Slice 2 — intelligence (Day 2)
- **T-022** [O2] `correspondence_history` — IMAP search for prior contact
- **T-023** [O1] Three subagents — INFRASTRUCTURE / IDENTITY / HISTORY, running in parallel
- **T-024** [O1] Prompt subagents to return **structured evidence, not prose**; narrow remits so they don't duplicate work
- **T-025** [O1] Cheap model for subagents, strong model for the lead
- **T-026** [O2] `detonate` MCP wrapper dispatching O1's sandbox job

## Slice 3 — the product (Day 3) ← *everything after this is cuttable*
- **T-030** [O2] `quarantine` over IMAP
- **T-031** [O2] `notify_impersonated` over SMTP
- **T-032** [O2] `create_block_rule`
- **T-033** [O2] `file_abuse_report` to the RDAP abuse contact
- **T-034** [O1] All four actions marked as approval-required in `agent.json` — **four sequential gates**, each showing what it will do. Configuration, not code
- **T-035** [O1] Warm-sandbox or snapshot strategy, **and** actually wire `detonate.js` (or its successor) to execute inside the Daytona sandbox job — cold start is 2–5 min and kills the demo. Currently `detonate.js` has zero Daytona integration; it's a plain Node module (§8, 2026-08-25)
- **T-036** [O3] LICENCE REQUIRED panel — renders TrueForge's approval request in our styling, Allow/Deny per gate. **Depends on T-002.** Four gates fire in sequence, not one modal

## Slice 4 — depth (Day 4)
- **T-040** [O1] Session persistence + resume — campaign dossier survives a restart
- **T-041** [O1] Error paths: sandbox dies, MCP times out, model returns garbage, redirect loop
- **T-042** [O4] Eval harness — 20 phish (phishing_pot) + 20 ham (SpamAssassin/Enron), report accuracy **and false-positive rate**
- **T-043** [O3] Spoken verdict — Web Speech API, ~1h
- **T-044** [O3] **UI polish block — book the afternoon, nothing else in it. This is the iPad**
- **T-045** [O2] SQLite caching so repeated missions don't re-hit crt.sh

## Cockpit (O3, from join day)
- **T-050** Scaffold + event-stream consumer, rendering `contracts/fixtures/` start to finish
- **T-051** Mission view — plan tree expanding as the agent works
- **T-052** Three evidence lanes streaming in parallel — *this is what makes subagents visible*
- **T-053** Detonation panel — redirect chain, then the screenshot of the fake portal
- **T-054** Verdict panel — plain English, ≤4 sentences, no jargon
- **T-055** Dossier view — past missions, resumable, campaign recognition
- **T-056** Reconnect handling — TrueForge survives reconnects, so the UI should, and it's demo-able

## Mission (O4, from join day)
- **T-060** Range: `docker compose up` → Mailpit + fake portal + `seed.sh`
- **T-061** 20 fixtures: **15 malicious, 5 legitimate that must NOT trip it**
- **T-062** `fake-portal/` — **fictional brands only** ("Northgate Trust", "Meridian Courier")
- **T-063** Skills: `triage-a-message`, `read-a-detonation`, `propose-actions`, `explain-to-a-human`
- **T-064** Qodo PR triage — daily, nothing merges unreviewed
- **T-065** README tested by a **clean clone on someone else's machine**
- **T-066** Write-up: how the agent uses TrueForge, primitive by primitive
- **T-067** Demo video — **4 hours on Day 5**, rough cut Day 4
- **T-068** Blog post (Field Report prize — one writer)
- **T-069** Day 4 cross-brief — each owner explains their area to the other three (rules 12 & 13)
- **T-070** Secret sweep — no tokens in repo, **no tokens visible in the video**
- **T-071** Daily social posts tagging WeMakeDevs + TrueFoundry

---

# §12 THE TEN WAYS WE WILL WASTE HOURS

Read aloud at kickoff. Re-read at the Day 3 standup.

| # | Trap | Cost | Rule |
|---|---|---|---|
| 1 | **MCP transport mismatch** (stdio vs HTTP/SSE) | 4h | Read the cookbook example **before** writing the server |
| 2 | **The chromium install loop** | 6h | Timebox 3h → text-mode fallback |
| 3 | **Gmail OAuth** — `gmail.modify` is restricted: consent screen, possible app review | 8h | **IMAP + app password.** 20 minutes. Decided matter |
| 4 | **Verifying DKIM ourselves** — DNS + canonicalisation | 2 days | Read the `Authentication-Results` header |
| 5 | **Dumping HTML into model context** | money + accuracy | Summarise inside the tool |
| 6 | **Fresh sandbox per detonation** — 2–5 min cold start | kills the demo | Snapshot or keep warm |
| 7 | **Tuning prompts before the pipeline runs** | 1 day | Bytes flowing end to end first |
| 8 | **Polishing UI against imaginary data** | rework | Build against `contracts/fixtures/` |
| 9 | **Trying to build a real security product** | the week | One narrow job, three-minute demo |
| 10 | **No contracts → merge hell on Day 3** | 1 day | 90 minutes on Day 0 buys the week |

## Smaller catches that will surprise us mid-week
- ⚠️ **Local fixtures have no `Authentication-Results` header** — it's added by the *receiving*
  server. Hand-write realistic ones or the identity subagent has nothing to read on Day 1
- ⚠️ **URLhaus is malware-focused.** Most phishing URLs aren't listed. **"Not listed" ≠ safe.**
  Never build a demo beat on a URLhaus hit — you'll get a shrug on camera
- ⚠️ **crt.sh is slow and 502s.** 5s timeout, cache to SQLite, never block a mission
- ⚠️ **Many ccTLDs have partial/no RDAP**, and GDPR redacts abuse contacts. *"Registration date
  not published"* is a valid finding, not a crash
- ⚠️ **Extract URLs with `lxml`, not regex.** Regex on HTML costs an evening
- ⚠️ **href ≠ anchor text is the highest-signal free feature.** Three lines of code
- ⚠️ **Don't base64 screenshots into tool results.** Write the PNG, return an ID
- ⚠️ **Never fire a real abuse report at a real registrar during testing.** Range mail server only
- ⚠️ Charset lies are common — wrap decoding in try/except, fall back to `latin-1`

---

# §13 DATA SOURCES

## Tier 1 — The Range (ships in the repo; **this is what judges run**)
`range/` → Mailpit + fake portal + `seed.sh`. 20 fixtures: 15 malicious across varied tactics
(credential phish, invoice fraud/BEC, CEO impersonation, fake courier, OTP theft, subscription
scam, malicious attachment) and **5 legitimate that must not trip it.**

*Rule 5 says judges must be able to run your code. Every other security submission will be
undemonstrable — "trust my video, I can't show you my inbox." A judge can clone ours and watch
the whole mission offline on their own laptop.*

## Tier 2 — Public corpora (**evals only, never the demo** — their URLs are years dead)
| Source | Gives | Where |
|---|---|---|
| **phishing_pot** | Raw `.eml`, actively collected | `github.com/rf-peixoto/phishing_pot` |
| **Nazario corpus** | ~4.5k hand-screened phish, 2015–2021 | `monkey.org/~jose/phishing/` |
| **SpamAssassin public corpus** | **Ham — our false-positive baseline** | `spamassassin.apache.org/old/publiccorpus/` |
| **Enron** | Legitimate business mail baseline | `cs.cmu.edu/~enron/` |

**The ham matters more than the phish.** An agent that flags everything is worthless, and
false-positive rate is the number that makes the write-up credible.

## Tier 3 — Live (one rehearsed shot in the video)
Our own spam folders → throwaway account. Unambiguously ours (rule 6). **Never committed.**

## Intel APIs
| API | Key | Note |
|---|---|---|
| RDAP (`rdap.org`) | none | age, registrar, abuse contact |
| crt.sh | none | *"cert issued 14 hours ago"* is a killer signal |
| URLhaus | free, `auth.abuse.ch` | weak signal only |
| ~~PhishTank~~ | ❌ | Registration closed since 2020 |

## Safety rules (put these in the README — judges notice)
1. Sandbox holds **no credentials**, no route back to our systems
2. **Never render remote images** — tracking pixels confirm a live address
3. Attachments: static unpack + hash lookup only. **No execution** in v1
4. Fixtures stored de-fanged (`hxxp://`), links rewritten to the Range
5. No real brand assets — fictional brands only
6. Live samples never committed

---

# §14 BUILD ORDER & SCHEDULE

| Slice | Runs end to end | Day |
|---|---|---|
| **1** | Hardcoded fixture → parse → one subagent → verdict → one gate → cockpit. **Ugly** | 1 |
| **2** | Three real subagents, real intel, real verdict with evidence | 2 |
| **3** | **Detonation. Four actions. Per-action grant/deny. Actions execute** ← *the product* | 3 |
| **4** | Dossier, evals, voice, error paths | 4 |

| Day | Focus | 10 PM gate |
|---|---|---|
| **0 · Sun 24** | Spikes + scaffold + Qodo + contracts | Spikes answered, logged in §6 |
| **1 · Mon 25** | Slice 1, ugly | 40-second recording of the ugly slice |
| **2 · Tue 26** | Slice 2 | Correct verdict on an unseen fixture |
| **3 · Wed 27** | Slice 3. **Nothing new after 10 PM** | Full mission runs live on the call |
| **4 · Thu 28** | Dossier, evals, **UI polish (iPad day)**, cross-brief | Eval number exists, rough cut recorded |
| **5 · Fri 29** | **FREEZE 12:00 IST.** Video (4h), README, write-up, blog | Everything but submit is done |
| **6 · Sat 30** | Final Qodo pass, clean run, **submit 18:00 IST** | Submitted with 6h spare |

**Standups:** 10:00 AM IST (15 min, plan) · 10:00 PM IST (30 min, integrate + run end to end).
If it doesn't run end to end, that's tomorrow's only priority.

---

# §15 COMMIT & PR DISCIPLINE — *this is the Best Code Quality track*

> *"Judges read your pull request history, so the review trail is the evidence. A repo with a
> single pull request opened an hour before the deadline will not win this one."*

- **`main` is protected. No direct pushes. Ever.**
- Branches: `<area>/<short-description>` → `tools/rdap-client`, `harness/spike-chromium`
- **PRs under ~400 lines.** A 2,000-line PR gets a useless review from Qodo *and* from humans
- **Every PR gets a Qodo review before merge.** Fix real findings; if you disagree, **say why in
  a comment** — that reply is part of the evidence
- `main` stays green. Break it, fix it before you sleep
- **Squash-merge**, so `main` reads as one clear change per PR
- Commit body explains **why**, not what — the diff already says what
- **No secrets, ever.** `.env.example` only. If a key touches a commit, **rotate it** — deleting
  the commit is not enough

**Conventional commits:**
```
feat(tools): add RDAP domain age lookup
fix(harness): cap redirect chain at 10 hops
docs(plan): record spike 1 outcome
chore(range): add 3 credential-phish fixtures
spike(harness): test chromium in daytona sandbox
```
Types: `feat` `fix` `docs` `chore` `test` `refactor` `spike`

**Rule 11 — AI disclosure is mandatory.** Every AI-assisted commit carries:
```
Assisted-by: Claude Code
```
Never add it to a commit written entirely by a human — the disclosure has to be accurate to be
worth anything.

**Rules 12 & 13 — we must understand our own code.** *Projects entirely generated by AI without
meaningful participant contribution, verification, or technical understanding may be rejected.*
**Never merge a PR you cannot explain line by line.** Day 4 cross-brief is booked, not optional.

---

# §15a QODO — what it's for, and what it isn't

**Yes, we use it. Install day one, then forget it exists.**

## Why, precisely
Judging criterion 04, scored on **every** submission regardless of track:
> *"Is TrueForge central to the project rather than a thin wrapper around a model, **and did Qodo
> review the pull requests on the way there?**"*

Six criteria, weighted equally. Skipping Qodo means walking into criterion 04 with half the
question unanswerable — on the UI track, on the TrueForge track, on all of them.

## What it costs
~10 minutes of setup. Then nothing. It comments on pull requests by itself.

## What it is
A dev tool. It reviews our pull requests with context from the whole repository, flags bugs and
logic gaps, and suggests fixes. **It never touches the product**, never appears in the
architecture, never runs at demo time.

## What it is NOT
- Not part of the agent
- Not something we build against or integrate with
- **Not a track we're chasing.** Best Code Quality is one Mac Mini split four ways. Best UI is an
  iPad *per member*. Rule 14: one team takes only one track. We aim at UI

## The one non-negotiable
**It cannot be retrofitted.** Their site: *"A repo with a single pull request opened an hour
before the deadline will not win this one."* Install before the first real commit, open PRs
instead of pushing to main, let it review, fix the real findings, and reply in a comment when you
disagree — that reply is part of the evidence too.

---

# §16 SUBMISSION CHECKLIST (rule 9)

- [ ] Public repo, readable and runnable (rule 5)
- [ ] README with setup steps, **verified by a clean clone on someone else's machine**
- [ ] Demo video ~3 minutes
- [ ] Write-up: what the agent does + **how it uses TrueForge**, primitive by primitive
- [ ] Blog post published and linked (Field Report prize)
- [ ] Agent runs on TrueForge, harness visibly doing real work (rule 3)
- [ ] Qodo installed at the start, PR trail reviewed all week
- [ ] Only our own tools/data/accounts; **no keys or personal data in repo or video** (rule 6)
- [ ] All code written 24–30 Aug (rule 7)
- [ ] AI disclosure complete (rule 11)
- [ ] All four can explain the architecture (rules 12, 13)
- [ ] TrueForge repo starred by all (Calling Card draw)
- [ ] Daily posts tagging WeMakeDevs + TrueFoundry (Radio Traffic)

**Track note (rule 14):** one team can only take one of the three judged tracks. **Best UI awards
an iPad to every member** — per person, the richest track for a team of four, and most teams
forfeit it by shipping the stock chat window.

---

# §17 THE DEMO (3:00) — written before the code, on purpose

| Time | Shot |
|---|---|
| 0:00–0:20 | An email that would fool you. "Your CFO wants an urgent transfer" |
| 0:20–0:45 | Forward it. Agent accepts. Three evidence lanes light up in parallel |
| 0:45–1:25 | **Sandbox detonation** — redirect chain resolving, then the screenshot of the fake portal. It asks for a password and posts it elsewhere |
| 1:25–1:50 | Evidence: domain 2 days old · cert issued yesterday · reply-to is a lookalike · your CFO has mailed you 214 times, never from here |
| 1:50–2:20 | 🔶 **LICENCE REQUIRED**, four times over. Each gate shows the literal request before it runs. Allow, allow, **deny**, allow — the denial is the shot that proves the gate is real |
| 2:20–2:40 | Granted actions execute for real. Quarantined. The real CFO warned |
| 2:40–3:00 | A phone. Plain English, spoken: *"This is fake. It is not your bank. Do not click it."* Cut to the harness diagram |

**If it isn't in this script, it isn't a priority.** Every proposed feature answers: *which second
does this appear in?*

---

# §18 HONEST ODDS

Build ≈ **45–60 engineer-hours**. Four people × six days × 5 realistic hours ≈ 120.
**~2× headroom**, which is right — half of hackathon time goes to integration, debugging, video.

| Outcome | Likelihood |
|---|---|
| Something working and submittable | ~90% |
| Slices 1–3 done by end of Day 3 | ~85% |
| **With screenshot detonation** | ~60% — hostage to T-001 |
| With text-mode fallback | ~95% |
| Plus dossier, evals, voice, polished UI | ~50% |

> **Every hour we lose this week will be lost to refusing a fallback, not to the work being too hard.**
