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
PHASE:        DAY 1 — SLICE 1 (ugly vertical slice) — **stale, see note below**
DATE:         2026-08-27
DAYS LEFT:    3
ACTIVE:       Owner 1 (Harness) · Owner 2 (Tools) · Owner 3 (Cockpit)
DORMANT:      Owner 4 (Mission)
TODAY'S GOAL: Slice 1 running end to end, ugly (O1) — three subagents now defined in agent.json, instructed to report structured evidence per T-024 (prompt guidance merged, runtime behavior still unverified — see BLOCKED ON). Intel sources + MCP transport settled, normaliser starting (O2); T-020 (domain_intel) and T-021 (url_reputation) both now fully complete on the `tools/` stack — 2 of the 3 planned Slice 2 read-only `imports-mcp` tools done, `correspondence_history` (T-022) still outstanding (§2). Contracts merged into main; Cockpit scaffold (T-050) now built against them, consuming the mission fixture end to end (O3).
BLOCKED ON:   T-015 live-fire test — no model provider configured; T-023/T-024 runtime verification — actual delegation and reporting *behavior* unobserved, not just JSON acceptance (§5)
LAST UPDATED: 2026-08-27 17:36 · T-024 (O1) merged into `main` as `43dda6f7c90a3ca9f9ae6f50ed5438a6f4e6c0df` (PR #17) — instructions now ask subagents to report structured JSON evidence (own tool's field names, no invented schema) instead of prose, plus explicit narrow-remit wording. Prompt guidance merged; actual runtime reporting format still unverified (§5). Qodo caught 2 real bugs on first review (IDENTITY missing the contract's required `from_address`; an ownership-wording ambiguity that could've dropped HISTORY's required `domain`) — both fixed and independently re-verified against `contracts/events.ts`/`cockpit/src/missionSource.ts` before pushing, re-review came back clean (0 Bugs/0 Rule violations/0 Skill insights). §2 already held T-025 in T-024's place, §11 already had T-024 removed — no further table changes needed. Contract drift found while building T-024 (`DomainIntel`/`UrlReputation` vs. real tool output) still open, logged in §8. T-050 (O3) done — `cockpit/` scaffold (Vite + React + TS) built, consumes `contracts/fixtures/mission-happy-path.json` end to end via a source/consumer split designed to swap in TrueForge's real SSE stream later without a rewrite (§4/§6 for detail). PR #1-#5, #12 (T-016), #13 (T-023), #16 (T-050), #17 (T-024) all merged into main; T-020/T-021 done but still stranded on `tools/domain-intel`, not yet merged up; live-fire still blocked on a model provider key
```

> Note (2026-08-27, O3): PHASE above says "DAY 1 — SLICE 1" but today is Day 3 per §14's own schedule and Slice 1's tasks are all done — flagging the staleness rather than silently reassigning it, since declaring the project's actual current slice/phase is a bigger call than T-050's scope covers (Slice 2's T-022/T-026 are still open — T-024 done, §4 — so "Slice 3" isn't clearly correct either). Whoever next does cross-owner bookkeeping should settle this.

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
| 1 | **T-051** | Mission view — plan tree expanding as the agent works | O3 | — | Direct follow-on to T-050 (just done) — the scaffold/consumer exists, this is the next Cockpit backlog item in order (§11); not reordering ahead of it without evidence |
| 2 | **T-022** | `correspondence_history` — IMAP search for prior contact | O2 | — | Last of the three planned Slice 2 read-only `imports-mcp` tools; `domain_intel`/`url_reputation` (T-020/T-021) are already done on `tools/domain-intel` |
| 3 | **T-025** | Cheap model for subagents, strong model for the lead | O1 | — | Next O1 Slice 2 backlog item, same theme as T-023/T-024 (just done) — a config change to `agent.json`'s per-subagent model, not new code |
| 4 | **T-026** | `detonate` MCP wrapper dispatching O1's sandbox job | O2 | — | Wires the already-working `harness/detonate.js` (T-014) into the MCP tool surface so the INFRASTRUCTURE subagent (T-023) can actually call it |

> Note (2026-08-26, O1, replacing the prior table): all four previous entries (T-016, T-010, T-011, T-012) are done and merged into `main` — confirmed via `gh pr view`/`git merge-base`, not assumed. Refilled from §11 per the existing selection rules (current slice first, then what unblocks other owners, then demo requirements): T-050 unblocks O3 (idle since joining, and §17's demo has nothing to show without a cockpit); T-022/T-026 are Slice 2's remaining current-slice work (T-024 done, §4). T-025 (cheap/strong model split) stays in backlog — a cost/config tweak, not blocking anything. `tools/domain-intel` (T-020+T-021, both done) still needs to merge up into `main` — not listed here since that's integration bookkeeping, not a backlog task.
> Note (2026-08-27, O3): T-050 done (§4) — swapped for T-051 in the same slot, per §11's Cockpit backlog order. Did not touch T-022/T-024/T-026 rows; no evidence either owner's status changed.
> Note (2026-08-27, O1): T-024 done (§4) — swapped for T-025 in the same slot, the next O1 Slice 2 backlog item in order. Also removed T-024 from §11 — it had been sitting in both tables since being picked, a pre-existing duplicate this cleans up as a side effect of finishing it, not a separate cleanup pass. Did not touch T-022/T-026/T-051 rows.

⏱ = has a timebox. See §3.

---

# §3 IN PROGRESS

> One row per active owner. Claude fills `Started` from `date` and checks elapsed time
> every few turns.

| ID | Owner | Started (IST) | Timebox | Fallback if it expires |
|---|---|---|---|---|
| _(none yet)_ | | | | |

> Note (2026-08-26): T-010 (the previous row) shipped and merged into `main` long ago (§4) — this table wasn't cleared when it finished. No other owner has evidence of an actively-timeboxed task right now.

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
2026-08-25 · T-015 · [O1] · One approval gate wired end to end, up to the point that needs a real model call. `harness/stub-mcp-server.js` — throwaway Streamable HTTP MCP server (TrueForge only supports `type: "remote"`/URL connectors, no local/stdio — confirmed against its own OpenAPI schema), one tool `quarantine_stub`. Registered live with TrueForge (`POST /settings/mcp-servers`, 201), tool discovered live (`GET /mcp-servers/{name}/tools`, 200, correct schema), and a test agent referencing `require_approval_for_tools: ["quarantine_stub"]` was accepted (`POST /agents`, only rejection was the expected "model provider not configured" 422) — result: **the gate wiring itself is proven correct**; the live-fire test (an actual `tool.approval_required` SSE event from a real turn) is deferred, see §5. `harness/agent.json` itself untouched — the stub connector only exists in a throwaway test payload, never the product config
2026-08-25 · T-014 (Qodo pass) · [O1] · Fixed 5 real bugs Qodo's PR #3 review found: fetch/DNS/timeout/malformed-redirect failures now return `{url, redirect_chain, error}` instead of throwing; one malformed form `action` no longer aborts analysis of the rest of the page (represented with `action_invalid: true` instead); HTML content-type check is case-insensitive; response body is read with a hard byte cap (`readBodyWithLimit`, streamed, never fully buffered) before parsing; non-HTML success responses now return the full documented shape including `summary`. 10/10 tests pass (7 new regression tests added). Declined one finding — see §8
2026-08-25 · T-003 · [O2] SPIKE 3 — all three intel sources confirmed live: RDAP via `rdap.org/domain/{domain}` (follow redirects) returns registration date + abuse contact; crt.sh reachable but 502ing on every attempt right now (matches known trap, mitigation unchanged); URLhaus `/v1/host/` and `/v1/urls/recent/` both confirmed working with the `Auth-Key` header already present in `.env` — added `.env.example` since none existed
2026-08-25 · T-004 · [O2] Read `bring-your-own-mcp` cookbook example (README, agent.json, mcp-server.mjs, package.json) end to end — settles trap #1 (transport mismatch) before any MCP code gets written
2026-08-26 · T-016 · [O3] · `contracts/events.ts` — TrueForge wire-level approval/session types copied verbatim from T-002's confirmed schema (§6), MCP tool result shapes from §10's tool table, plus a `MissionEvent` discriminated union mapping one variant onto each stage of §10's architecture diagram (message received → per-lane evidence → detonation → verdict → 4 sequential licence gates → action executed → complete), so Cockpit's T-050/T-036 have a single stream to bind to. `contracts/fixtures/mission-happy-path.json` — one full 20-event BEC/invoice-fraud mission (fictional "Northgate Trust" domain, per §13 rule 5) matching §17's demo content, all four gates granted — result: type-checked clean with `npx -p typescript tsc --noEmit --strict contracts/events.ts` (repo has no TypeScript toolchain of its own yet — none of T-050's tooling exists, so this used a throwaway npx run, nothing added to the repo); JSON fixture validated with `python3 -m json.tool` and by hand-checking every event against the `.ts` shapes. T-050 (Cockpit scaffold) now unblocked, pulled into §2 NEXT UP in its place. PR #12 opened same day
2026-08-26 · T-016 (Qodo remediation, round 1) · [O3] · Qodo's PR #12 review found 4 real bugs and 2 rule findings — fixed all 6, see §6/§8 for the decisions. Bugs: `DetonationResult`/`DetonationForm` were an invented shape, not `harness/detonate.js`'s real output — rewrote both as a two-variant union modeled directly on the producer (`redirect_chain` is now `{url,status}[]`, matching detonate.js's actual pushes; forms use the real field names `action_origin`/`method`/`cross_domain`/`asks_password`; error results no longer require `summary`/`final_url`, matching detonate.js's error-path returns). `EvidenceEvent` previously let any lane pair with any evidence type — replaced with a discriminated union pairing lane to its valid evidence shape(s), with a compiled proof it's enforced (`contracts/events.typecheck.ts`, verified to genuinely fail without its `@ts-expect-error` guard). Rule findings: added a maintenance-process note directly in `events.ts`'s header; PR size only partly addressed (464 lines, still over ~400) — result: `tsc --noEmit --strict` clean on both files; fixture re-validated field-by-field with a runtime structural checker (not committed). Pushed, PR #12 still open
2026-08-26 · T-016 (Qodo remediation, round 2) · [O3] · Actually resolved the PR-size finding rather than documenting an exception: re-formatted `contracts/fixtures/mission-happy-path.json` (flat/repetitive objects collapsed to single lines, still valid multi-line JSON, no event or field dropped) — 190 → 91 lines, `contracts/` diff 464 → 365. No type-safety or coverage traded away. Re-ran the same validation (tsc strict + runtime structural check, 20/20 pass) — result: total PR diff (incl. PLAN.md) now under 400 lines. Pushed, PR #12 still open, awaiting Qodo re-review + 2nd approval
2026-08-26 · T-015 (Qodo pass) · [O1] · Re-checked PR #4 against current main first: findings #1/#4/#5/#6/#7 from Qodo's review (attached to stale commit 5a31de1) all trace to `detonate.js`/`detonate.test.js`/`.gitignore`, which landed in PR #3 and aren't part of PR #4's diff at all — no rebase was needed, PR #4 already sits on current main. Fixed the two real bugs/rule-violations left: `quarantine_stub` now caps `message_id` so the serialized response stays under the ~2KB MCP limit (`truncated` flag added, regression test in `stub-mcp-server.test.js`); added `harness/test/approval-gate-verification/` (throwaway test-agent JSON + `verify-approval-gate.sh` + exact cleanup instructions) so the T-015 gate-wiring proof (§4 above) is reproducible from a clean checkout — `harness/agent.json` still untouched. The 400-line PR-size finding is documented, not code-fixed — see §6. 12/12 tests pass. Pushed to PR #4, not merged — waiting on Qodo to review the new HEAD
2026-08-26 · T-015 (Qodo pass 2) · [O1] · Qodo's incremental review re-scans full file content at HEAD, not a diff against current main (see §7) — so it re-flagged `detonate.js`/`detonate.test.js`/`.gitignore` even though they're identical to main. Two of those findings turned out genuinely worth fixing on their own merits, so fixed for real this time instead of re-documenting: (1) **SSRF guard added to `detonate.js`** — the initial URL and every redirect hop now resolve the hostname and refuse loopback/RFC1918/link-local/cloud-metadata addresses (checked against the resolved IP, not just the hostname, so DNS-rebinding-style domains are caught too); `allowPrivateNetworkTargets: true` is the explicit, narrow opt-in `detonate.test.js`'s own fixture now uses, plus a new default-refusal regression test. This is a real production SSRF fix, not a Daytona workaround, and needed no Daytona credentials. (2) PR description now explicitly names `.gitignore` and its rationale (Rule 2880666). Re-verified the PR-size finding (Rule 2880655) is genuinely not reducible: lockfile is 106 packages with no duplicate/platform-variant bloat, all transitively required by the 3 declared dependencies — kept documented, not code-changed. 13/13 tests pass
2026-08-26 · T-015 (Qodo pass 3) · [O1] · Dismissed findings #4 (.gitignore undocumented) and #7 (approval-gate reproducibility) via `@qodo dismiss` replies on their review-comment threads, citing current evidence already in the PR (description names `.gitignore`; `harness/test/approval-gate-verification/` provides the reproducible setup) rather than changing working code to appease stale evidence — Qodo's own reply independently confirmed #7's evidence was stale. Final state before merge: 0 Bugs, 1 Rule violation (the documented, genuinely-unfixable PR-size finding), 0 Skill insights. Merged into main, resolving the PLAN.md conflict against PR #5 (T-003/T-004) in the same merge commit
2026-08-26 · T-016 (PLAN.md conflict resolution) · [O1] · PR #12's branch was behind main (opened before PR #4/#5 merged) — merged current main in, resolved the resulting PLAN.md conflict mechanically (this block), left `contracts/events.ts`/`events.typecheck.ts`/`fixtures/mission-happy-path.json` untouched. `tsc --noEmit --strict` re-run clean on both `.ts` files post-merge; harness `node --test` also re-run (13/13) since the merge touched shared PLAN.md history. Confirmed Qodo's PR #12 review is clean at current HEAD: 0 Bugs, 0 Rule violations, 0 Skill insights, all 6 original findings resolved. Remaining blocker is exactly one thing: the CLAUDE.md `/contracts` 2-human-approval rule — zero human approvals exist yet (`reviewDecision` empty). Not merged, implementation not altered
2026-08-25 · T-020 · [O2] `domain_intel` (`tools/imports_mcp/domain_intel.py`) — RDAP registration/registrar/abuse-contact + crt.sh cert age, wired as a second `imports-mcp` tool. Each source degrades independently to `available=false` + a note instead of raising; crt.sh results cached in-memory (never caches a transient failure, only a real answer). crt.sh was down the entire time this was built — that's a live-fire test of the fallback, not a hypothetical one. Hit and fixed a real local SSL bug along the way (see §7). 12 new tests (8 mocked-network unit tests + 3 tool-wiring contract tests + 1 more live end-to-end test alongside T-012's over the real transport) — 24/24 total pass
2026-08-26 · T-020 (Qodo pass) · [O2] Fixed 5 findings from PR #9's review: PR itself was split in two (implementation + wiring tests vs. the full unit-test suite) since the combined diff ran to 692 lines against the 400-line rule; `domain_intel()` now enforces the ~2KB MCP response budget, shortening free-text fields and setting an explicit `truncated` flag rather than ever emitting an unbounded response; the crt.sh cache now actually honours `CRTSH_CACHE_TTL_SECONDS` (was storing bare results with no timestamp, so nothing ever expired); RDAP and crt.sh parsing are now robust to technically-valid-but-malformed JSON (wrong types at any level) via `isinstance` guards plus a parsing-boundary `try/except`, so a malformed response from one source degrades independently instead of raising and starving the other source of its own lookup; the integration test's live RDAP-registrar-string assertion (`"MarkMonitor" in ...`) is gone, replaced with structural assertions that hold regardless of what RDAP actually returns. 11 new regression tests — 35/35 total pass
2026-08-26 · T-020 (Qodo pass 2) · [O2] Fixed 2 more findings: a non-list `events` value (e.g. a string) was being treated as "no registration event found" — `available: true` — instead of a malformed response, since a string is iterable and silently produced zero matches rather than raising; RDAP's own JSON-decode failure path (`raise_for_json=True`) had no regression test, nor did crt.sh's. `events` is now strictly required to be a list before any iteration; 1 existing test corrected (now asserts the malformed-shape degradation instead of the old harmless-ignore behavior) plus 2 new tests (RDAP JSON-decode-failure with crt.sh independent, crt.sh JSON-decode-failure with RDAP independent) — 37/37 total pass
2026-08-26 · T-020 (PR #9 + #14 merged) · [O1] · PR #9 (implementation + wiring/contract tests + integration-test updates) and PR #14 (the exhaustive `domain_intel` unit-test suite, split out purely to satisfy the 400-line rule — see the Qodo-pass entry above and §6) both merged: PR #9 as `1aebf464c556aed91fbc87dca94fe167f891fe52` into `tools/imports-mcp-skeleton` (first resolved a `PLAN.md`/`tools/requirements.txt` merge conflict against that moved base — kept `mcp>=2.0` from the base plus `requests`/`truststore` from this branch, no dependency lost either side), PR #14 as `5ca7fa537928899e373b2ac4da8f96a7edf5b4df` on top of that. Both PRs' remaining Qodo findings were independently verified as false positives against current code (not new fixes) and dismissed with cited line-by-line evidence: PR #9's "domain_intel response uncapped," "malformed responses abort tool," "PR exceeds 400 lines," and "crt.sh cache never expires" all traced to evidence that didn't match the already-fixed code; PR #14's "JSON failures remain untested" was factually wrong — the two JSON-decode-failure tests it claimed were missing were verified present and passing (confirmed by directly invoking the mock to prove `resp.json()` genuinely raises, not just an unused kwarg). Post-merge, confirmed directly: `domain_intel.py` and `test_domain_intel.py` both present on `tools/domain-intel`; full non-integration `tools/` suite (includes T-010/T-012's own tests too) — 59/59 pass. **T-020 is now fully complete** — implementation, wiring, and its exhaustive unit-test suite are all merged together. Not yet on `main`; `tools/domain-intel` still needs to merge up through the rest of the `tools/` stack
2026-08-25 · T-021 · [O2] `url_reputation` (`tools/imports_mcp/url_reputation.py`) — URLhaus exact-URL lookup, wired as a third `imports-mcp` tool. Confirmed exact response field names live against the real API first (`query_status`/`threat`/`tags`/`url_status`/`date_added`) before writing tests against them. "Not listed" always carries an explicit weak-signal note per trap #8, never returned as a clean bill of health. Same graceful-degradation shape as T-020 (missing key / 401 / non-200 / network error / bad JSON all become `available=false` + a note, never a raise). 11 new tests (8 mocked-network unit + 3 wiring/live) — 37/37 total pass, including two more live end-to-end calls over the real transport (URLhaus is reliably up, so unlike T-020's crt.sh case this one asserts on the actual verdict)
2026-08-26 · T-021 (Qodo pass) · [O2] · Fixed all 4 Qodo findings on PR #10: (1) `url_reputation()` now runs every return path through `_cap_response()` (Rule 2880706) — trims `tags` first, then truncates `note`/`url` as strings, until the serialized response is back under ~2KB, with a `truncated` flag and per-field `omitted` indicator. (2) A 200 with valid-but-non-object JSON (`null`, an array, a bare string) used to crash `data.get(...)` with `AttributeError` — added an `isinstance(data, dict)` check right after the JSON-decode, falling into the same graceful `available: false` path as the other malformed-response cases; 2 new tests (`null`, list). (3) The live URLhaus integration test now skips by default (`URLHAUS_AUTH_KEY` unset → skipped, not failed) instead of requiring the secret in the default suite, and its assertion is structural (shape/types) rather than pinned to URLhaus's current, mutable verdict for `https://example.com/` — deterministic behavior stays covered by the 12 mocked tests in `test_url_reputation.py`. (4) PR description now explicitly names `PLAN.md` as the root-level/cross-owner file touched and what it records. All 15 tests directly in scope (`test_url_reputation.py` + `test_server_url_reputation_contract.py`) pass; the 2 url_reputation tests in `test_server_integration.py` also pass individually/in isolation. Pushed, not merged — waiting on Qodo to re-review the new HEAD
2026-08-26 · T-021 (PR #10 merged) · [O2] · `tools/url-reputation` rebased onto the then-current `tools/domain-intel` (post PR #9+#14 merge) to pick up the T-020 Qodo-fix history it had branched before — 2 real conflicts, both in `PLAN.md` (§1 `LAST UPDATED` and §4 DONE, both additive, interleaved rather than one side dropped) plus a third file (`tools/tests/test_domain_intel.py`) that git resolved automatically by recognizing the branch's own copy as equivalent to already-applied history, so `domain-intel`'s corrected strict-events test and JSON-decode-failure coverage were kept intact, not reverted. Force-pushed with `--force-with-lease`, then PR #10's base was retargeted from the stale `tools/domain-intel-tests` to current `tools/domain-intel` (diff dropped from 940/-24/12 files to the correct 432/-6/7 files, matching T-021's actual changes only). Qodo did not produce any review or check-run for the rebased HEAD (`30b8bd7e8e336ccc7753f6920b2f2c039b51de0e`) despite the push and the retarget — confirmed repeatedly (0 check-runs, commit status `pending`, the only review on file still pinned to the pre-rebase commit `d9e213d`). Given repeated confirmation that no review would land, merging was authorized as an **explicit, one-time exception** to the "never merge before Qodo has reviewed" rule (§6) — not a standing policy change. Immediately before merging, independently re-verified: PR mergeable/clean, base `tools/domain-intel`, head still exactly `30b8bd7`, working tree clean, 15/15 T-021 tests, 24/24 T-020 regression tests, 80/80 full suite, diff scoped to T-021's own 7 files only. Merged (squash) as `766d30520393504b09184736232b2b414095365d` into `tools/domain-intel`. **T-021 is now fully complete and merged** — same as T-020, `tools/domain-intel` (now carrying both) has not yet been merged up into `main`
2026-08-26 · T-023 · [O1] · `harness/agent.json`'s `instructions` now **asks** the root agent to delegate to three named subagents in parallel (configuration via prompt, not new code — CLAUDE.md "don't rebuild the harness"), matching §10's architecture table field-for-field: INFRASTRUCTURE (`domain_intel`, `url_reputation`, `detonate`), IDENTITY (no tool — display-name vs. Reply-To/Return-Path + lookalike-domain checks on already-parsed fields), HISTORY (`correspondence_history`). Structured (non-prose) evidence output is explicitly left to T-024, not attempted here. `agent.json` still valid JSON, same top-level schema already runtime-confirmed in T-013/T-017 (only the `instructions` string value changed) — result: **written, not yet runtime-verified**, no local TrueForge instance was running this session to POST it against a live server; harness `node --test` re-run clean (13/13, unaffected — no JS changed) as a regression check only, not a substitute for that verification
2026-08-26 · T-023 (Qodo pass) · [O1] · Qodo's PR #13 review found 1 real Bug: the initial `harness/README.md`/PLAN.md wording documented the three-subagent topology as if `dynamic_sub_agents` platform-enforces it. Independently verified against TrueForge's own docs (`trueforge.dev/key-features/subagents`) — confirmed the finding: the root agent's own model decides at runtime whether/how to delegate, generating its own instructions via the built-in `create_sub_agent` tool (not from our prose), and every spawned subagent gets the **full** root tool set — no per-agent scoping exists. Fixed by rewording README.md/this file to state plainly that `instructions` is best-effort prompt guidance to the root's delegation decision, not enforced configuration — "IDENTITY: no tool call" is a request, not a boundary; "exactly three subagents" is what we're asking for, not a guarantee. The approach itself (prompt-only, no custom delegation code) stays correct — Qodo's own assessment agreed building real enforcement would duplicate native harness behavior. `agent.json`'s `instructions` text itself wasn't changed — it was already phrased as guidance to the model, not a claim about platform behavior; only the docs describing it were overclaiming
2026-08-27 · T-050 · [O3] · `cockpit/` scaffold — Vite + React + TS (stack spike + decision, see §6). `src/missionSource.ts` is the event-source abstraction: `fixtureEventSource()` plays `contracts/fixtures/mission-happy-path.json` back one `MissionEvent` at a time (an async generator, not a static array dump — matches the shape a real SSE stream will demand), and `assertMissionEvent()` runtime-validates every event (unknown `type`, or a `mission.evidence` whose `lane` doesn't pair with a real evidence shape, throws instead of rendering silently wrong — the runtime equivalent of the exact bug class Qodo's PR #12 review caught in the type itself, finding #4). `src/useMissionEvents.ts` consumes the source in order into React state; `src/MissionView.tsx` renders each event as one human-readable line built from its typed fields (not `JSON.stringify` — a `switch` over `MissionEvent["type"]`, and a nested one over `EvidenceEvent["lane"]`, both exhaustive against the contract's discriminated unions). No parallel event model invented; every type imported from `../../contracts/events`, none redeclared, per that file's own maintenance rule — result: `npm run build` (`tsc -b && vite build`, strict) clean; dev server verified serving all modules incl. the cross-folder `../../contracts/fixtures/mission-happy-path.json` import (200 via Vite's `/@fs/` resolution); direct Node execution of `missionSource.ts` confirmed all 20 fixture events consumed in exact fixture order, and separately confirmed `assertMissionEvent` genuinely rejects an unknown `type` and an invalid `lane` (not just always-passes) while accepting a valid event; `harness/node --test` 13/13 and `contracts/`'s own `tsc --noEmit --strict` re-run clean (unaffected, neither folder touched). T-051 (mission view/plan tree) is next — not attempted here
2026-08-27 · T-024 · [O1] · `harness/agent.json`'s `instructions` now tells each subagent to report back structured evidence, never prose — a small JSON object built only from the fields its own tool call(s) actually returned (INFRASTRUCTURE: one object per tool it called — `domain_intel`/`url_reputation`/`detonate`'s own result fields, omitting a key entirely for a tool it didn't call rather than fabricating one; IDENTITY: `display_name`/`reply_to`/`return_path`/`lookalike_domain`/`lookalike_of`, computed from the parsed message, no tool call; HISTORY: `correspondence_history`'s own result fields) — plus an explicit "never a field another subagent owns" line addressing T-024's other half (narrow remits, no duplicated evidence). The lead, not the subagents, turns that evidence into the final plain-English verdict. Same prompt-only approach as T-023 (configuration, not code — `dynamic_sub_agents` still has no schema-enforcement mechanism to build against). **Found and deliberately did not use** `contracts/events.ts`'s `DomainIntel`/`UrlReputation` types as the target shape: neither matches the real tool output (`domain_intel.py` nests results under `rdap`/`cert`; `url_reputation.py` has `available`/`threat`/`url_status`/`date_added`/`truncated` fields the contract omits entirely) — a real, pre-existing contract/producer drift, logged in §8 rather than fixed here since `/contracts` needs 2 approvals and is out of this task's scope. `agent.json` still valid JSON, same schema as T-013/T-017/T-023 (only `instructions` changed) — result: **written, not yet runtime-verified**, same constraint as T-023 (no local TrueForge instance this session); `node --test` re-run clean (13/13, unaffected — no JS changed), regression check only
2026-08-27 · T-024 (Qodo pass) · [O1] · Fixed 2 real bugs Qodo's PR #17 review found, both verified directly against `contracts/events.ts` and `cockpit/src/missionSource.ts`'s runtime validator before fixing, not just accepted on Qodo's say-so: (1) IDENTITY's field list omitted the required `from_address` and included a `return_path` the contract doesn't have — `IdentityEvidence` (and `isIdentityEvidence`'s runtime check) requires exactly `from_address`/`display_name`/`reply_to`/`lookalike_domain`/`lookalike_of`; a missing `from_address` genuinely fails Cockpit's validator (`fail(index, ...)`), confirmed by reading the check, not assumed. Fixed by adding `from_address` and keeping `return_path` as a bonus field alongside it (validator doesn't reject extras, only checks the required ones are present and typed). (2) The "never a field another subagent owns" line was genuinely ambiguous: `domain_intel` and `correspondence_history` both have their own `domain` field, and `CorrespondenceHistory`'s contract requires HISTORY's `domain` — a literal reading of "ownership" could tell the model to drop HISTORY's required `domain` just because a different tool's output happens to share that key name. Reworded to make "own remit" explicitly about judgment (only IDENTITY decides lookalike-domain, only INFRASTRUCTURE calls its three tools), not field names — a shared key name across two tools' own outputs is never a reason to drop or rename either one. `harness/README.md` updated to match both fixes. `agent.json` re-validated as JSON; `node --test` re-run clean (13/13, unaffected). Pushed to PR #17, not merged — waiting on Qodo to re-review the new HEAD
2026-08-27 · T-024 (PR #17 merged) · [O1] · Qodo re-reviewed the fixed HEAD clean (0 Bugs/0 Rule violations/0 Skill insights, both prior findings resolved) — merged into `main` as `43dda6f7c90a3ca9f9ae6f50ed5438a6f4e6c0df`. Confirmed directly (not assumed): `git show origin/main:harness/agent.json` contains the structured-evidence instructions including `from_address`. **T-024 is now fully complete and on `main`** — same runtime-verification gap as T-023 still applies (§5): written and merged, but no local TrueForge instance has observed a real turn's actual delegation/reporting behavior yet

---

# §5 BLOCKED

| ID | Owner | Blocked on | Since | Who can unblock |
|---|---|---|---|---|
| T-015 live-fire test | O1 | No model provider configured anywhere (§1 DO THIS FIRST still unchecked). Gate wiring itself is proven (§4); what's missing is watching a real turn actually emit `tool.approval_required` and resuming it | 2026-08-25 | Whoever configures a model provider key + spend cap in TrueForge's settings UI (`localhost:8790`) — enter it there, never paste it into chat |
| T-023/T-024 runtime verification | O1 | The `instructions` field is accepted-schema-safe (same as T-013/T-017), but that's not the open question — the open question is *behavior*: whether a real turn actually spawns three subagents matching these names/remits, whether an IDENTITY-labeled one stays tool-free in practice, and (T-024) whether reports actually come back as structured JSON instead of prose, given `dynamic_sub_agents` enforces none of it (§4, Qodo pass) | 2026-08-26 | Whoever next has TrueForge running locally + a model provider key: run a real turn against a suspicious-email fixture and observe the actual `create_sub_agent` calls/names/tool use/report format, not just POST `harness/agent.json` and check the status code |

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
2026-08-25 · [O2] · `imports-mcp` is Streamable HTTP via the official **Python** MCP SDK's `MCPServer` — **not** Express/JS. The `bring-your-own-mcp` cookbook (which is Node/Express) only settled the transport *shape* (Streamable HTTP, not stdio); the language/SDK is Python per the decision directly below, since `/tools` is Python. Runs `stateless_http=True` together with `json_response=True` — the default SSE response mode was later found (T-012) to hang forever on a tool error under statelessness, logged in §7 once that lands — registered in TrueForge via Settings → Connectors then referenced by name in `agent.json`
2026-08-25 · [O2] · `/tools` is Python — stdlib `email` for RFC822 parsing, `lxml` for HTML (per the trap in §12), MCP server on the official Python MCP SDK's streamable-HTTP transport to match T-004's findings
2026-08-26 · [O3] · Contract types must be modeled on the real producer's actual output, not the tidiest shape that fits the architecture diagram — Qodo's PR #12 review caught `DetonationResult` inventing field names (`asks_for_password`/`posts_cross_domain`) that don't exist in `harness/detonate.js`. Going forward, any `contracts/events.ts` type wrapping an existing producer reads that producer's code first, PLAN.md §10's table second
2026-08-26 · [O3] · `contracts/fixtures/mission-happy-path.json` represents all four licence gates as **granted** — "happy path" read literally as the full mission completing with nothing blocked. §17's specific "allow, allow, deny, allow" sequence is a deliberate dramatic beat for the demo video, not this base fixture. A separate fixture (e.g. `mission-with-denial.json`) can be added later if Cockpit needs to test the deny-rendering path before the real gate demo is rehearsed
2026-08-26 · [O1] · Qodo's PR #4 (T-015) review re-checked against the correct base: `.gitignore` and all of `detonate.js`/`detonate.test.js` landed in PR #3 (main), so findings #1, #4, #5, #6, #7 from the review attached to stale commit 5a31de1 do not apply to PR #4's actual diff at all — nothing to fix there, no rebase needed (PR #4 already sits on current main). Fixed the three findings that are real for this PR's diff: `quarantine_stub`'s response now caps `message_id` to stay under the ~2KB MCP limit (Rule 2880706) with a `truncated` flag and a regression test; added `harness/test/approval-gate-verification/` (throwaway test-agent payload + script) so the T-015 gate-wiring proof is reproducible from a clean checkout, `harness/agent.json` still untouched. Left the 400-line PR-size finding (Rule 2880655) as a documented position, not a code change — see next line | Findings #1/#4/#5/#6/#7 N/A to PR #4; #3 and #8 fixed with tests; #2 documented |
2026-08-26 · [O1] · **PR #4 size (Rule 2880655) — documented, not resolved by deleting anything.** `harness/package-lock.json` is machine-generated by `npm install` from `package.json`'s 3 declared dependencies (MCP SDK, zod, and their transitive tree); it is not hand-authored and isn't meaningfully reviewed line-by-line. The actual hand-authored diff in this PR (`package.json`, `stub-mcp-server.js` + its new test, the approval-gate-verification throwaway files, README/PLAN updates) is well under 400 lines; the lockfile alone accounts for the overage. Deleting the lockfile to shrink the diff was rejected — it would break reproducible installs (`npm ci`), which CLAUDE.md requires we not do for a "required dependency file." Documented on the PR description for Qodo/reviewers instead, same posture as the Rule 2880752 precedent above | Documented in PR #4 description; lockfile kept |
2026-08-26 · [O1] · **Rule 2880752 (localhost/SSRF) resolved differently on PR #4 than on PR #3 — a real fix, not another decline.** PR #3's decline (row above, 2026-08-25) still stands as the correct call for *that* PR: `detonate.test.js`'s fixture is a same-process unit-test double with no Daytona integration to violate. On re-evaluation for PR #4, though, Qodo's evidence pointed at a genuine gap independent of Daytona: `detonate()` had no check that the initial URL or a redirect resolves to a private/internal address, which is a real SSRF risk in production regardless of sandboxing. Fixed with a resolved-IP guard (loopback/RFC1918/link-local/cloud-metadata refused by default) plus an explicit `allowPrivateNetworkTargets` opt-in for the test fixture only — no Daytona credentials needed, no fabricated dependency | Implemented in `detonate.js`; PR #3's original decline entry left unmodified as the historical record for that PR |
2026-08-26 · [O1] · Findings #4 (.gitignore) and #7 (approval-gate reproducibility) dismissed on PR #4 via `@qodo dismiss` rather than further code changes — both were already substantively fixed (PR description, `harness/test/approval-gate-verification/`) and Qodo's incremental re-review doesn't refresh evidence for findings whose originally-cited files weren't the ones edited (see §7). Qodo's own chat reply independently confirmed #7's evidence was stale before the dismissal | Dismissed with reasoning on each finding's thread, not code-changed |
2026-08-26 · [O1] · T-020's PR #9 was split into two PRs (#9 + #14) purely to satisfy the 400-line rule (§15), not because `test_domain_intel.py`'s exhaustive unit-test suite was optional — confirmed directly from the split commit's own message: "...so it's still reviewed as part of finishing T-020's Qodo pass — just as its own PR... The file isn't deleted, only untracked here; it reappears whole in the next branch." Both halves were required for T-020 to be complete: PLAN.md's own §4 record already claimed test coverage (the JSON-decode-failure regression tests, the corrected malformed-events test) that only physically existed in PR #14 before it merged. Both PRs merged — see §4 | Both required, both merged; treat a "PR split for line-count" as splitting one task's review, not splitting what's actually required to ship it |
2026-08-26 · [O2] · PR #10 (T-021) merged under an explicit, one-time authorized exception to the "never merge before Qodo has reviewed" rule — Qodo never produced a review or check-run for the exact final HEAD (`30b8bd7`) after a rebase, force-push, and base retarget, confirmed repeatedly with no change. All other merge preconditions were independently re-verified immediately beforehand (mergeable/clean, correct base/head, 15/15 T-021 tests, 24/24 T-020 regression tests, 80/80 full suite, diff scoped to T-021's own files). This is a one-off for PR #10 only — it does not authorize skipping Qodo review on any other PR |
2026-08-27 · [O3] · Cockpit stack: Vite + React + TypeScript, no state-management/UI-kit library. Nothing in PLAN.md/CLAUDE.md picked a frontend stack before now, so this was T-050's own small spike, not a preference — picked because it's the simplest option that (a) imports `contracts/events.ts` directly, satisfying that file's own "Cockpit code imports types from here, never redeclares them" rule (TS + a bundler that resolves a cross-folder `../../contracts` path — plain JS or a non-TS framework couldn't do this cleanly), (b) needs zero extra deps to prove the T-050 scope (fixture in, events out, rendered), and (c) doesn't foreclose T-051-056's componentized, multi-panel, streaming-update needs the way reaching straight for vanilla DOM manipulation would. State management/routing/UI-kit deliberately left out — not needed yet, add only when a real task needs one
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
| 2026-08-25 | O1 | Running `node`/`npm` from WSL2 against this repo (`/mnt/c/...`, which is also OneDrive-synced) is **pathologically slow for anything touching `node_modules`** — a plain dynamic `import()` of an installed package hung 8+ seconds with zero output, no error. Copying the same `node_modules` to WSL's native filesystem (`/tmp/...`) and running from there: instant, worked first try | For any Node work done from WSL against this repo: either `npm install` and run from a native-WSL path (`/tmp/...` or `~/...`), copying source in, not `/mnt/c` directly — or accept real slowness. TrueForge itself is unaffected (its own `npx` cache lives in the WSL user profile, not `/mnt/c`) |
| 2026-08-25 | O2 | crt.sh returned 502 on 7/7 live attempts against two different domains, in-line with the known trap | Ship the 5s timeout + SQLite cache from day one (T-045) — don't wait for it to fail in front of a judge |
| 2026-08-25 | O2 | No `.env.example` existed even though a real `.env` with `URLHAUS_AUTH_KEY` was already in the repo (gitignored, untracked — never committed) | Added `.env.example` with the key name and no value; do this for every new secret going forward |
| 2026-08-26 | O1 | Assumed Qodo's incremental PR review re-diffs against current `main` on every push, same as GitHub's own Files-changed tab. It doesn't: after pushing a commit that only touched 5 files (confirmed against GitHub's own `files` API), Qodo's updated review still cited `detonate.js`/`detonate.test.js`/`.gitignore` line ranges as PR evidence — files untouched since PR #3 merged and absent from GitHub's actual diff. It re-scans the full file tree at HEAD against its standing rule set, not a git diff, so account-level rules (2880752, 2880666) re-fire on any file in the tree regardless of whether this PR's own commits touched it. Worse: even after the underlying fix (PR description, new files), the displayed finding stayed unchanged/stale across two more HEAD updates — only a `@qodo dismiss` reply on the finding's thread flips its displayed status; there's no "refresh evidence" trigger | Before treating a Qodo finding as "not this PR's problem," check GitHub's actual PR `files` list (`gh pr view --json files`), not just local `git diff main...branch`. If a finding is genuinely fixed but Qodo still shows it open with unchanged evidence, don't chase it with more code changes — dismiss it on its own thread with the current evidence cited |
| 2026-08-26 | O1 | T-020's §4 DONE entry ("Qodo pass 2," written before the PR split) claimed specific tests existed and passed ("1 existing test corrected... plus 2 new tests... 37/37 total pass"), but the commit that entry describes (`8a3d4e0`, PR #9's own final commit) touches only `PLAN.md` and `domain_intel.py` — zero test files. The tests the entry claims only existed in the later PR #14 split. Anyone reading PR #9 alone, without also checking PLAN.md's git-blame or the sibling PR, would have no way to tell the claimed coverage wasn't actually in that PR | When a task's Qodo-fix pass gets split across two PRs mid-stream, write (or amend) the §4 entry to say explicitly which PR each part landed in — don't let one entry's claimed test count silently span code that ends up in a different PR than the one being reviewed |
| 2026-08-26 | O2 | Distinct from the "stale evidence" issue above (§7, 2026-08-26/O1): after force-pushing a rebased branch (`--force-with-lease`) and then retargeting the PR's base branch via the API, Qodo produced **no** review or check-run at all for the new HEAD — not stale evidence, no evidence, confirmed by 0 `check-runs`, commit status `pending`, and no new PR comment, checked repeatedly over time. A normal push seems to trigger Qodo fine; a force-push combined with a base retarget apparently did not | If a PR's history is rewritten (rebase/force-push) and/or its base is changed, don't assume Qodo will automatically re-review the new HEAD the way it does for an ordinary push — check for an actual new review/check-run before relying on one, and budget time to trigger it manually or escalate if it never appears |
| 2026-08-26 | O1 | PR #12 (T-016) merged into `main` at `cbe5d52` (2026-08-26T10:03:59Z), but §1/§4/§5 kept saying "still needs a 2nd human approval, not merged" through two separate later conflict-resolution merges on two different branches (PR #13 twice, plus main's own PR #15 sync) — nobody re-checked `gh pr view` against the actual claim, they just carried the existing text forward while resolving unrelated conflicts | When resolving a PLAN.md conflict that touches a PR's merge status, verify that status against `gh pr view <n> --json state,mergedAt,mergeCommit` before carrying either side's wording forward — a conflict-resolution merge is exactly the moment stale status silently propagates, since neither side's author knew the other had gone stale |
| 2026-08-27 | O1 | T-024's first draft designed IDENTITY's structured-evidence field list straight from T-023's old *analysis* prose ("compare display name against Reply-To and Return-Path") without re-checking it against `contracts/events.ts`'s already-existing `IdentityEvidence` type — result: missing the contract's required `from_address`, plus an extra `return_path` field the contract never had. Unlike `DomainIntel`/`UrlReputation` (§8), `IdentityEvidence` has no separate real producer to diverge from — it's derived from parsed-message fields same as this prompt is, so the contract *was* the authoritative shape here and got overlooked anyway | When a task's output has an already-defined contract type (check `contracts/events.ts` and its consumer's runtime validator, e.g. `cockpit/src/missionSource.ts`), design directly from that type's field list, not from older prose describing the *analysis*, not the *output shape* — the two can drift even when both were written by the same task |

---

# §8 SUGGESTED CHANGES TO PLAN

> The plan is wrong sometimes. Write it here, raise it at standup, then edit the sections below.

| Date | Owner | Suggestion | Status |
|---|---|---|---|
| 2026-08-25 | O1 | Plan assumed `harness/agent.json` is a file TrueForge itself reads. It isn't — agents are created via `POST /api/v1/agents` with a `manifest` body (model, instructions, mcp_servers incl. `require_approval_for_tools`, config). We're keeping `agent.json` as our repo-committed source of truth for that manifest and seeding it with a `curl` POST — matches the spirit of "configuration, not code" (§10) just via API instead of a config file TrueForge auto-loads | Adopted, see `harness/README.md` |
| 2026-08-25 | O1 | Qodo's PR #3 review flagged `detonate.test.js`'s fixture server for using `127.0.0.1` as a rule violation, citing the "Daytona can't reach localhost" trap. **Declined, on reconsideration with fuller evidence.** The only documented rule (CLAUDE.md #9, PLAN.md §12, both verbatim-checked) says the *production fake portal* must live inside Daytona because a remote sandbox can't dial back to a laptop — a network-reachability fact about one specific target, not a blanket ban on localhost. Neither file mentions test fixtures. Implementing Qodo's literal remediation (host the test fixture inside a live Daytona sandbox) would need Daytona credentials we don't have, spin a sandbox per test run (directly violating CLAUDE.md trap #4: "never spin a fresh sandbox per detonation"), and break a judge's clean-clone test run (rule 5, T-065) — trading one claimed violation for three real ones. **What Qodo did get right, and what we missed the first pass:** §10's architecture diagram draws detonation (redirect chain, form targets — exactly what `detonate.js` does) as running *inside* Daytona in the intended production pipeline, and T-014's own backlog line calls the text-mode fallback "still genuine sandboxed work." So production `detonate.js` genuinely is meant to eventually execute inside a Daytona sandbox — that wiring doesn't exist yet (T-035, scope clarified below). That's a real, separate gap from this test-fixture question, out of T-014's scope/timebox as built. Replied on the Qodo thread with this full reasoning | Declined, reasoning posted on PR #3's review thread; T-035 scope clarified |
| 2026-08-25 | O1 | **The exact conflict on finding #3 (Qodo Rule 2880752), stated precisely.** Rule 2880752 ("Disallow running the detonation fake portal on localhost," `app.qodo.ai/rules/2880752`) is a *standing, account-level Qodo Compliance Rule* — not a per-review inference. It reads: "detonation-related fixtures are required to run at a Daytona sandbox endpoint," with no carve-out for test-only fixtures. This is broader than its source text (CLAUDE.md #9 / PLAN.md §12), which names one specific case: the *production* fake portal must be reachable *by a real, remote Daytona sandbox*, because Daytona can't dial back to a laptop. `detonate.test.js`'s fixture triggers neither the wording's condition nor its reason — the code under test (`detonate.js`) has no Daytona integration (§11 T-035, unbuilt) and isn't invoked from inside any sandbox in this test; both the fetcher and the fixture run in the same local Node process, so there is no remote-sandbox-to-laptop gap to cross. The conflict is therefore rule-scope vs. architecture, not evidence vs. architecture: satisfying the rule as written would mean building Daytona orchestration as a prerequisite for a task explicitly scoped as the fallback *because* that spike didn't land, and would itself break CLAUDE.md trap #4 and rule 5/T-065 (§8, row above). Rule stays as configured — no repo-level Qodo config exists to change (checked: no `.qodo*`/`pr_agent*` file in the repo; the rule lives entirely on the Qodo dashboard) — and no change was made to it. Declined via a `@qodo dismiss` reply on the finding's thread instead, since that records the decision on the PR without touching rule configuration | Declined; dismissal requested on PR #3, rule config untouched (needs explicit approval to change) |
| 2026-08-25 | O1 | Whoever's on Windows for real dev work should expect to run TrueForge from WSL2 (with Node installed inside the distro), not native Windows — it segfaults there. Worth a line in the top-level README's setup steps once written (T-065 checks this on clean clone) | Open |
| 2026-08-26 | O3 | §10's MCP tool table has no dedicated tool/shape for the IDENTITY lane ("display-name vs reply-to, lookalike domain" per the architecture diagram) — INFRASTRUCTURE maps to `domain_intel`/`url_reputation`/`detonate`, HISTORY maps to `correspondence_history`, but IDENTITY analyzes fields already present on the parsed message rather than calling a new tool. Added a minimal `IdentityEvidence` type to `contracts/events.ts`, worded directly from §10's own diagram text rather than invented. Update (2026-08-26, Qodo remediation): `EvidenceEvent` now pairs each lane to its valid evidence shape(s) as a discriminated union (Qodo PR #12 finding #4) — `identity` can only carry `IdentityEvidence`, enforced by the compiler, not just convention | Open, still needs O1/O2 confirmation the identity subagent needs no MCP tool of its own |
| 2026-08-26 | O3 | PR #12's line count (finding #5): round 1 only got it from 495 to 464, still over ~400. Round 2 found genuine remaining bulk in the fixture — mechanical/repetitive flat objects (gate approvals, evidence) formatted one-field-per-line for no real readability gain — and collapsed them to single-line objects, still valid indented JSON, no event/field dropped. `/contracts` diff: 464 → 365; total PR diff now under 400. Lesson: check for real formatting bulk before concluding a size limit can't be met | Resolved |
| 2026-08-26 | O3 | PR #4 (`harness/approval-gate-stub`) and the PR #5 tools stack (`tools/spike-intel-apis` onward) have each independently edited §2 NEXT UP / §11 backlog differently while both unmerged — PR #4 added T-010 to NEXT UP while the tools stack was already doing T-010 for real, and the two disagree on T-016's position. This branch only removed T-016 (done) and added T-050 in its place; it did not touch T-015/T-003/T-004's rows or try to reconcile the two branches' conflicting edits, since that's O1/O2's call, not O3's, and guessing wrong here would destroy real planning information from one of them | Open, needs O1/O2 reconciliation at merge time |
| 2026-08-27 | O1 | `contracts/events.ts`'s `DomainIntel`/`UrlReputation` interfaces don't match the real tool output, found while writing T-024's structured-evidence instructions and deliberately not using them as the target shape. `domain_intel()` (`tools/imports_mcp/domain_intel.py`, merged on `tools/domain-intel`) returns `{domain, rdap: {available, registrar, registration_date, abuse_contact, note}, cert: {available, earliest_seen, age_days, note}, truncated}` — nested under `rdap`/`cert`, with `available`/`note` on each; the contract's `DomainIntel` is flat (`{domain, registration_date, registrar, abuse_contact, cert_issued_at}`) with no `available`/`note`/`truncated` at all and a `cert_issued_at` field that doesn't exist on the real output. `url_reputation()` similarly returns `available`/`threat`/`url_status`/`date_added`/`truncated`/`omitted` that the contract's `UrlReputation` (`{url, listed, tags}`) omits entirely. Same class of bug as Qodo's PR #12 finding #4 (`DetonationResult` invented, not modeled on `detonate.js`) — these two just weren't caught because `tools/domain-intel` hasn't merged into `main` yet, so nothing has type-checked them against each other. Not fixed here: `/contracts` needs 2 approvals (CLAUDE.md) and this is a harness-scoped task | Open, needs O1/O2/O3 to update `DomainIntel`/`UrlReputation` (or split into an "available/note" wrapper matching the other tools) once `tools/domain-intel` merges into `main` and both files can actually be checked against each other |

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
*(T-011, T-012 pulled into §2 NEXT UP — nothing left here for Slice 1.)*

## Slice 2 — intelligence (Day 2)
- **T-022** [O2] `correspondence_history` — IMAP search for prior contact
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
