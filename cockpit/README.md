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
