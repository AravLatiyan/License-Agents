# cockpit (Owner 3)

The UI. See root `PLAN.md` for the plan and `CLAUDE.md` for the rules.

## Stack (T-050)

Vite + React + TypeScript. No frontend framework/stack existed anywhere in
PLAN.md or CLAUDE.md before this task — picked as the simplest maintainable
option that can import `contracts/events.ts` directly (a hard requirement:
that file's own maintenance rule says Cockpit code imports types from there,
never redeclares them), render the fixture, and later swap to a real SSE
stream without a rewrite. No state-management or UI-kit dependency added —
not needed yet, and CLAUDE.md says not to add one before it is.

## Run it

```bash
cd cockpit
npm install
npm run dev      # dev server
npm run build    # tsc -b && vite build — type-checks contracts/events.ts too
```

## What's here (T-050 scope only)

- `src/missionSource.ts` — the event-source abstraction. `fixtureEventSource`
  plays `contracts/fixtures/mission-happy-path.json` back one event at a
  time; a real `trueForgeEventSource` (T-002/PLAN.md §6: `POST /sessions` →
  `POST /sessions/{id}/turns` with `stream:true` → SSE, `tool.approval_required`,
  resume via `user.tool_approval`, reconnect via `GET /turns/{id}/subscribe`)
  is the only thing later work should need to add — everything downstream
  only ever sees `MissionEvent`.
- `assertMissionEvent` in the same file — runtime validation so a malformed
  event (unknown `type`, or an evidence event whose `lane` doesn't pair with
  a real evidence shape — the exact class of bug Qodo's PR #12 review caught
  in the *type* once, see `contracts/events.typecheck.ts`) throws instead of
  silently rendering wrong.
- `src/useMissionEvents.ts` — consumes a `MissionEventSource` in order,
  accumulating events as they arrive.
- `src/MissionView.tsx` — renders the accumulated events as a simple ordered
  list, one short human-readable line per event built from its typed fields.
  Deliberately not the finished evidence-lane/detonation/verdict panels —
  those are T-052/T-053/T-054.

`contracts/fixtures/mission-happy-path.json` represents all four licence
gates as granted (§6, 2026-08-26) — there is no deny case to render yet.

## Live TrueForge source (T-039)

`src/trueForgeSource.ts` is the `trueForgeEventSource` this README and
`missionSource.ts` have both named as the intended swap-in since T-050. It opens
a real session and streaming turn over TrueForge's HTTP/SSE API and feeds every
raw wire event through the T-037 translator (`harness/translate/`), which is the
only thing that knows how TrueForge's 12 generic event types map onto this app's
`mission.*` vocabulary.

**It is opt-in, not the default.** With no environment set, the app plays the
fixture exactly as before — a clean clone with no server running must still show
the full mission (rule 5 / T-065), and §17's demo depends on that fallback.

```bash
VITE_TRUEFORGE_URL=http://localhost:8790/api/v1 \
VITE_TRUEFORGE_INPUT="$(cat ../tools/fixtures/01-credential-phish.eml)" \
npm run dev
```

`VITE_TRUEFORGE_AGENT` defaults to `universal-imports`, the name
`harness/agent.json` registers. The status line shows which source is active.

**Two things it deliberately does not do**, both because the evidence for them
does not exist yet:

- **No reconnect/resume.** `resumableStream.ts` (T-056) is built, tested and
  ready, but resuming needs an `after_sequence_number` cursor and nothing in
  TrueForge's OpenAPI spec publishes a sequence number on any event body or list
  wrapper — event `id` is a monotonic ULID string. The cursor is most likely the
  SSE `id:` frame field, which cannot be confirmed without watching one live
  turn. `parseSseFrames` already surfaces each frame's `id`, so wiring resume is
  small once that is observed (PLAN.md §8).
- **No approval submission.** Posting `user.tool_approval` back is T-036's live
  half and belongs to the Allow/Deny buttons, not to a read-only event source.
