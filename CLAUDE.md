# CLAUDE.md — read this at the start of every session

You are working on **UNIVERSAL IMPORTS**, a hackathon project with a hard deadline of
**30 Aug 2026, 18:00 IST**. Four people share this repo. **`PLAN.md` is the only planning file** —
the plan, the task board, progress, decisions and errors all live there, and you keep it current.

Staying in sync matters more than any individual piece of code.

---

## 🔁 SESSION START — do this unprompted, before anything else

1. `git pull`
2. Read **`PLAN.md`** — at minimum §1 (Live Status), §2 (Next Up), §3 (In Progress),
   §5 (Blocked) and the last 5 lines of §6 (Decisions)
3. Run `date` so you know the real time in IST
4. Work out which owner you're working as. **If it's not obvious, ask** — don't guess
5. **Report back in three lines**, then present the menu:

```
PHASE: <§1 phase> · Day <n> · <days left> to deadline
BLOCKED: <§5, or "nothing">
IN PROGRESS: <§3 row for this owner, with elapsed time, or "nothing">
```

6. Then show **§2 NEXT UP** as a numbered menu and **stop**:

```
What do you want to work on?

  1. T-001 · SPIKE 1 — chromium in a Daytona sandbox        [O1 · 3h ⏱]
     Highest-risk unknown in the project. Everything downstream depends on it.

  2. T-002 · SPIKE 2 — approval payloads + event streaming  [O1 · 2h ⏱]
     Decides the cockpit's core interaction; blocks Owner 3 when they join.

  3. T-003 · SPIKE 3 — URLhaus key, RDAP, crt.sh            [O2 · 2h ⏱]
     Cheap, confirms three of our four evidence sources exist.

  4. T-004 · Read the bring-your-own-mcp cookbook example   [O2 · 1h]
     One hour here saves four of transport debugging.

Pick a number, or tell me something else you need.
```

**Wait for the choice. Do not start work until they've picked.** If they ask for something not on
the menu, do it — but say whether it's in §11 Backlog or genuinely new, and if it's new, add it to
§8 Suggested Changes.

Do not skip this ritual because the conversation seems to start mid-task. They may have switched
machines, and other owners may have merged since.

---

## ▶️ WHEN A TASK IS PICKED

1. Add a row to **§3 IN PROGRESS**: ID, owner, `date` timestamp, timebox, fallback
2. Remove it from §2 (it comes back only if abandoned)
3. Confirm the timebox aloud and name the fallback **before starting**
4. Work. **One task at a time — never two.**

## ⏱️ WHILE WORKING — enforce the timebox against the user

Check elapsed time against §3 every few turns. You have `date`; use it.

- **30 min left:** *"About 30 minutes left on T-001's timebox. Worth thinking about the fallback."*
- **Expired:** stop the current line of work and say it plainly:

> "T-001's timebox expired 20 minutes ago. The plan says take the text-mode fallback and move on.
> Shall I log the fallback and start on it?"

They agreed to these timeboxes in writing, while calm. **Hold them to it.** Do not help them keep
debugging past a timebox — that is the single most likely way this project runs out of week.

Any single bug that eats **90 minutes**: stub it, log it in §7, move on, return later.

---

## ✅ WHEN A TASK IS FINISHED — update PLAN.md yourself, unprompted

Do all of this, then show the new menu:

1. **§4 DONE** — append `YYYY-MM-DD · T-XXX · [Owner] · what shipped — result`
2. **§3** — delete the row
3. **§2** — delete the completed task, then **pull replacements from §11 Backlog so NEXT UP holds
   exactly 4 again.** Choose by: current slice first, then what unblocks other owners, then what
   the demo script (§17) needs. If a spike's result changed the plan, prefer tasks that follow
   from the *new* reality, not the old one
4. **§6 DECISIONS** — one dated line for anything settled, with the reason. **Log it the moment
   it's decided, never batched**
5. **§7 ERRORS** — anything that cost time, so nobody pays it twice
6. **§8 SUGGESTED CHANGES** — anything the plan got wrong
7. **§1 LIVE STATUS** — update `LAST UPDATED`, and `BLOCKED ON` if it changed
8. Commit `PLAN.md` alongside the code, then remind them to open the PR
9. **Present the refreshed §2 menu** in the same format as session start

Also update §5 BLOCKED the moment something blocks, not at the end of the session.

### Task IDs
Sequential within their series — `T-0XX`. New tasks that aren't in §11 get the next free ID and go
into §11 first, then §2. Never invent a task straight into NEXT UP without recording it.

---

## 🚨 HARD RULES

### Git
- **NEVER commit directly to `main`.** Branch: `<area>/<short-description>`
- **NEVER commit a secret.** If one is staged, stop and tell them to **rotate it** — removing the
  commit is not enough
- Conventional commits: `feat(tools):` `fix(harness):` `docs(plan):` `chore(range):` `test(eval):`
  `refactor(...)` `spike(harness):` — subject under 72 chars
- **PRs under ~400 lines.** If a change grows past that, stop and split it — a 2,000-line PR gets
  a useless review from Qodo *and* from humans
- **Never merge before Qodo has reviewed.** If they ask you to merge something unreviewed, say so.
  The review trail is scored (criterion 04) and cannot be retrofitted
- Add this trailer to every commit **you** wrote:
  ```
  Assisted-by: Claude Code
  ```
  Required by rule 11. **Never add it to a commit the user wrote entirely themselves** — the
  disclosure has to be accurate to be worth anything.

### Understanding (rules 12 & 13 — projects may be *rejected* for this)
- After writing anything non-trivial, **explain what you wrote and why**, briefly, in plain terms
- If they're about to merge something they haven't understood, say so
- Prefer boring readable code over clever code. Another human has to defend this to a judge

### Scope
- If a request falls outside the current task, ask whether to switch or add it to §8
- If a proposed feature doesn't appear in the demo script (§17), say so before building it
- **Only edit your owner's folder.** Cross-folder changes need a heads-up in the PR description
- `contracts/` needs a PR with 2 approvals — never edit it casually

---

## 🧰 DON'T REBUILD WHAT THE HARNESS ALREADY DOES

TrueForge provides these. We **configure** them in `agent.json` and settings — we never
reimplement them, and suggesting we do is a scoring mistake as well as a waste of the week
(criterion 04 rewards TrueForge being *central*, not wrapped):

- **Approval gates.** Mark a tool as approval-required. TrueForge pauses, shows the JSON request,
  and renders Allow/Deny. Ours are **four sequential per-tool-call gates**, not one modal with
  four checkboxes
- **Sandbox lifecycle.** The agent requests a sandbox; the harness spins it up and tears it down.
  We only write *what runs inside it* — the detonation script, chromium, the fake portal
- **Subagent delegation, session persistence, reconnect survival, model switching, skill loading**

If a task starts to look like building one of these, stop and say so.

## ❌ KNOWN TRAPS — never walk into these, never suggest them

1. **Never use the Gmail API.** `gmail.modify` is a restricted scope: consent screen, possible app
   review, a full day gone. **IMAP + app password.** Decided matter, not a preference
2. **Never verify DKIM/SPF ourselves.** Read the `Authentication-Results` header
3. **Never return raw HTML to the model.** Summarise inside the tool; every MCP response under ~2KB
4. **Never spin a fresh sandbox per detonation** — 2–5 min cold start kills the demo. Snapshot or
   keep one warm
5. **Never parse HTML with regex.** Use `lxml`
6. **Never fire a real abuse report at a real registrar during testing.** Range mail server only
7. **PhishTank is unusable** — registration closed since 2020, still closed. Don't suggest it
8. **URLhaus is malware-focused, not phishing-focused.** "Not listed" ≠ safe. Never build a verdict
   or a demo beat on a URLhaus hit
9. **Daytona is remote and cannot reach `localhost` on their laptop.** The fake portal runs
   *inside* the sandbox
10. **Don't tune prompts before the pipeline runs end to end.** Bytes first, quality second
11. **Local `.eml` fixtures have no `Authentication-Results` header** — it's added by the receiving
    server. They must be hand-written into every fixture
12. **Don't base64 screenshots into tool results.** Write the PNG, return an ID
13. **Cold start is a demo problem, not a capability one.** If chromium installs but the second
    run is still slow, the fix is a snapshot or a warm sandbox — not more install debugging
14. **Qodo is a dev tool, never part of the product.** It reviews our PRs and nothing more —
    never integrate with it, never build against it, never put it in the architecture. It is half
    of judging criterion 04, scored on every submission regardless of track, so it must be
    installed from day one and every PR must go through it. But we are **not** chasing the Best
    Code Quality track itself — Best UI pays an iPad per member and a team can only take one track

---

## 🎯 WHAT WE'RE BUILDING

An agent that takes a suspicious email, **detonates it in a sandbox**, sends three subagents after
the infrastructure, the identity and the correspondence history, then proposes four irreversible
actions and **stops until a human grants the licence** for each one.

Judged on six criteria, weighted equally: potential impact · creativity · technical excellence ·
use of sponsor tools · **control and safety** · presentation.

**The qualifying test:** a judge must see the harness *reach a real tool, run code in the sandbox,
and stop for a person.* If a change doesn't serve one of those three, question it out loud.
