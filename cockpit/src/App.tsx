import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import missionHappyPath from "../../contracts/fixtures/mission-happy-path.json";
import { Inbox } from "./Inbox";
import { deleteAllMessages, fetchMailpitInbox, markAllRead, type InboxMessage } from "./mailpitSource";
import { MissionContextPanel } from "./MissionContextPanel";
import { buildApprovalGates } from "./missionPlan";
import { fixtureEventSource } from "./missionSource";
import { ReadingPane, type InvestigationBanner } from "./ReadingPane";
import { createTrueForgeMission } from "./trueForgeSource";
import { useMissionEvents } from "./useMissionEvents";
import type { ApprovalDecisionHandler } from "./ApprovalPanel";
import type { MissionEvent } from "../../contracts/events";

// The fixture is loaded as unknown, not assumed to already be MissionEvent[]:
// TypeScript's JSON-module inference widens string literals (e.g. "type") to
// `string`, so it can't actually prove the shape - assertMissionEvent does
// that for real, at runtime, one event at a time.

// T-039: the live source is opt-in, not the default. Point VITE_TRUEFORGE_URL
// at a running TrueForge (e.g. http://localhost:8790/api/v1) and this app
// drives a real turn through the T-037 translator instead of replaying the
// fixture. Left opt-in deliberately: a clean clone with no server running
// must still show the full mission (rule 5 / T-065), and §17's demo depends
// on that fallback existing. Everything downstream only ever sees
// MissionEvent and cannot tell which source produced it.
const liveBaseUrl = import.meta.env.VITE_TRUEFORGE_URL;
const liveAgentName = import.meta.env.VITE_TRUEFORGE_AGENT ?? "universal-imports";
const liveInput = import.meta.env.VITE_TRUEFORGE_INPUT;

// The real inbox. Same opt-in-with-graceful-fallback shape as the mission
// source above: point this at a running Mailpit (range/docker-compose.yml
// publishes 8025) and the inbox shows the real mailbox; unreachable, and the
// app still shows the one message its own mission is about (built below from
// mission.message_received), so a clean clone with nothing running still
// demos correctly.
//
// Defaults to `/mailpit-api`, Vite's own dev-server proxy (vite.config.ts) -
// never a bare cross-origin `http://localhost:8025` - because Mailpit
// rejects any cross-origin request by default and nothing configures it
// otherwise. `VITE_MAILPIT_URL` stays a real opt-in override for a setup
// that's already handled its own CORS (or a production build with a
// server-side proxy of its own), not the default path.
const mailpitBaseUrl = import.meta.env.VITE_MAILPIT_URL ?? "/mailpit-api";

// T-046: the live mission carries a submit path beside its event source. On
// the fixture path there is no mission and no handler, so the Allow/Deny
// buttons stay disabled exactly as they were.
const liveMission =
  liveBaseUrl && liveInput
    ? createTrueForgeMission({ baseUrl: liveBaseUrl, agentName: liveAgentName, input: liveInput })
    : null;

const source = liveMission ? liveMission.source : fixtureEventSource(missionHappyPath as unknown[]);

const sourceLabel = liveBaseUrl && liveInput ? "live TrueForge" : "fixture playback";

/** "Alex Morgan <a.morgan@example.com>" -> "a.morgan@example.com". Falls
 *  back to the whole string if it isn't the angle-bracket form - `from` is
 *  untrusted upstream data (RDAP/the message itself), never assumed to be
 *  well-formed. */
function addressFromHeader(from: string): string {
  const match = /<([^>]+)>/.exec(from);
  return (match ? match[1] : from).trim().toLowerCase();
}

function verdictLabel(v: "malicious" | "suspicious" | "legitimate"): string {
  return v === "legitimate" ? "Legitimate" : v === "malicious" ? "Malicious" : "Suspicious";
}

function App() {
  const stableSource = useMemo(() => source, []);
  const { events, status, error } = useMissionEvents(stableSource);

  // A human's decision produces events the stream itself can never carry:
  // TrueForge's turn stream has nothing between tool.approval_required and the
  // next turn.done, so `mission.approval_resolved` (and whichever gate that
  // releases) is constructed locally by the code that made the decision.
  // Held beside the streamed events rather than pushed into useMissionEvents,
  // which stays a read-only consumer.
  const [decisionEvents, setDecisionEvents] = useState<MissionEvent[]>([]);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  // Gates with a decision already in flight. Without this, the buttons stay
  // live during the async POST, so a double-click (or an Allow then a Deny)
  // sends two resumes for the same gate and appends two resolution events,
  // leaving the displayed outcome dependent on response order (Qodo, PR #85).
  // A licence decision is exactly the wrong thing to let race.
  const [pendingGates, setPendingGates] = useState<ReadonlySet<number>>(new Set());

  const onDecision = useCallback<ApprovalDecisionHandler>((decision) => {
    if (!liveMission) return;
    let alreadyPending = false;
    setPendingGates((prev) => {
      if (prev.has(decision.gateIndex)) {
        alreadyPending = true;
        return prev;
      }
      return new Set(prev).add(decision.gateIndex);
    });
    if (alreadyPending) return;

    void liveMission
      .submitApproval(decision)
      .then((produced) => setDecisionEvents((prev) => [...prev, ...produced]))
      .catch((err: unknown) => setDecisionError(err instanceof Error ? err.message : String(err)))
      .finally(() =>
        setPendingGates((prev) => {
          const next = new Set(prev);
          next.delete(decision.gateIndex);
          return next;
        }),
      );
  }, []);

  const allEvents = decisionEvents.length === 0 ? events : [...events, ...decisionEvents];

  // The inbox: real Mailpit messages where reachable, falling back to a
  // synthetic single row for whichever message this mission is actually
  // investigating (see the module comment above on mailpitBaseUrl).
  const [liveInbox, setLiveInbox] = useState<InboxMessage[] | null>(null);
  const reloadInbox = useCallback(() => {
    let cancelled = false;
    void fetchMailpitInbox(mailpitBaseUrl).then((messages) => {
      if (!cancelled) setLiveInbox(messages);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  // Polled, not fetched once: nothing here is hardcoded (it's always real
  // Mailpit data, current message count included), but a one-shot fetch
  // would still miss mail a real backend delivers after page load. Mailpit
  // has no documented push/websocket endpoint in the vendored spec
  // (range/mailpit-api.json) to subscribe to instead - polling is the
  // honest choice given what's actually verified to exist, not a shortcut.
  // Every consumer downstream (messages/investigatedId's useMemo, the
  // investigated row's pinned id) already tolerates `liveInbox` changing
  // under it - built for the live-reconnect case, T-056 - so this needed
  // no other code to change to become correct.
  useEffect(() => {
    const cancelInitial = reloadInbox();
    const interval = setInterval(reloadInbox, 5000);
    return () => {
      cancelInitial();
      clearInterval(interval);
    };
  }, [reloadInbox]);

  // Mailbox-level controls (mailpit-topbar) - real Mailpit API calls, not
  // decoration. Both re-fetch the inbox afterward so the list reflects what
  // actually happened rather than an assumed outcome. `mailboxActionError`
  // exists because both calls used to fail silently on a non-ok response -
  // the confirm() dialog below is pure client JS and always shows even when
  // the actual request (e.g. against a stale dev-server proxy) 404s, so a
  // failure needs its own visible state, not just an absent effect.
  const [markingAllRead, setMarkingAllRead] = useState(false);
  const [deletingAll, setDeletingAll] = useState(false);
  const [mailboxActionError, setMailboxActionError] = useState<string | null>(null);
  const onMarkAllRead = useCallback(() => {
    setMarkingAllRead(true);
    setMailboxActionError(null);
    void markAllRead(mailpitBaseUrl)
      .then((result) => {
        if (!result.ok) setMailboxActionError(`Mark all read failed: ${result.detail}`);
      })
      .finally(() => {
        setMarkingAllRead(false);
        reloadInbox();
      });
  }, [reloadInbox]);
  const onDeleteAll = useCallback(() => {
    // Irreversible (Mailpit wipes the whole mailbox) - confirm before
    // calling it, same as any other hard-to-reverse action.
    if (!window.confirm("Delete every message in this mailbox? This can't be undone.")) return;
    setDeletingAll(true);
    setMailboxActionError(null);
    void deleteAllMessages(mailpitBaseUrl)
      .then((result) => {
        if (!result.ok) setMailboxActionError(`Delete all failed: ${result.detail}`);
      })
      .finally(() => {
        setDeletingAll(false);
        reloadInbox();
      });
  }, [reloadInbox]);

  // Search + tag filter - both client-side over the already-fetched list
  // (Inbox.tsx §7/8: this codebase deliberately avoids Mailpit's own
  // `/api/v1/search` query grammar elsewhere, correspondence_history.py's
  // own T-022 decision - "unverified query grammar" - so filtering data
  // already on hand is the established, consistent choice, not a shortcut).
  const [searchQuery, setSearchQuery] = useState("");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [tagsMenuOpen, setTagsMenuOpen] = useState(false);
  const tagsMenuRef = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    if (!tagsMenuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      if (tagsMenuRef.current && !tagsMenuRef.current.contains(e.target as Node)) setTagsMenuOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [tagsMenuOpen]);

  const messageEvent = allEvents.findLast(
    (e): e is Extract<MissionEvent, { type: "mission.message_received" }> => e.type === "mission.message_received",
  );

  const { messages, investigatedId } = useMemo(() => {
    const live = liveInbox ?? [];
    if (!messageEvent) return { messages: live, investigatedId: null as string | null };

    const investigatedAddress = addressFromHeader(messageEvent.message.from);
    const matched = live.find((m) => m.from.address.toLowerCase() === investigatedAddress);
    const otherLive = matched ? live.filter((m) => m !== matched) : live;

    // The investigated row's id is always the mission's own message_id, not
    // Mailpit's row id - even once a live match arrives. The live fetch is
    // async and can resolve after the user has already selected this row
    // (built from `messageEvent` alone, before any match existed); if
    // `investigatedId` changed identity out from under a live `selectedId`
    // comparison, the panel would wrongly fall back to "no investigation has
    // been run" the instant Mailpit answered. Real fields (subject/date/
    // tags) are still taken from the match once one exists - only the id
    // stays pinned. No subject/date exists at all without a match
    // (ParsedMessage has neither, contracts/events.ts) - left null rather
    // than guessed; Inbox renders that honestly ("(no subject)").
    const investigatedRow: InboxMessage = matched
      ? { ...matched, id: messageEvent.message.message_id }
      : {
          id: messageEvent.message.message_id,
          from: { name: messageEvent.message.display_name, address: investigatedAddress },
          subject: null,
          date: null,
          snippet: null,
          tags: [],
          read: true, // no live message behind this row - nothing unread about it
          mailpitId: null, // no live match - nothing for the reading pane to fetch a body from
        };
    return { messages: [investigatedRow, ...otherLive], investigatedId: investigatedRow.id };
  }, [liveInbox, messageEvent]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  // A freshly opened message always starts with the drawer open, if it has
  // an investigation to show one for - same "start clean per selection"
  // rule as MissionContextPanel's own remount-per-`key` behaviour below.
  const [drawerOpen, setDrawerOpen] = useState(true);
  useEffect(() => {
    setDrawerOpen(true);
  }, [selectedId]);

  const selectedMessage = messages.find((m) => m.id === selectedId) ?? null;
  const isInvestigatedSelection = selectedId !== null && selectedId === investigatedId;

  const verdictEvent = allEvents.findLast((e): e is Extract<MissionEvent, { type: "mission.verdict" }> => e.type === "mission.verdict");
  const failedEvent = allEvents.findLast((e): e is Extract<MissionEvent, { type: "mission.failed" }> => e.type === "mission.failed");
  const investigating = Boolean(messageEvent) && !verdictEvent && !failedEvent;

  // What ReadingPane's injected banner says - the only thing about this
  // message that isn't real, un-modified Mailpit content. `null` for any
  // message other than the one this session's mission actually investigated
  // (Inbox.tsx's own `investigatedId` contract), so opening an ordinary
  // Mailpit message never implies an investigation that was never run.
  let banner: InvestigationBanner | null = null;
  if (isInvestigatedSelection) {
    const toggleText = drawerOpen ? "Collapse ▾" : "Open investigation ▸";
    if (investigating) {
      banner = {
        status: "investigating",
        leftText: "Investigating this message…",
        rightText: `${allEvents.length} event${allEvents.length === 1 ? "" : "s"} so far`,
      };
    } else if (failedEvent) {
      banner = {
        status: "investigating",
        leftText: failedEvent.cause === "error" ? `Investigation failed: ${failedEvent.message}` : `Investigation cancelled: ${failedEvent.reason}`,
        rightText: toggleText,
        onClick: () => setDrawerOpen((v) => !v),
      };
    } else if (verdictEvent) {
      const gates = buildApprovalGates(allEvents);
      const pendingCount = gates.filter((g) => !g.executed && g.resolved !== "deny").length;
      banner = {
        status: verdictEvent.verdict,
        leftText: (
          <>
            This message was investigated — <strong>{verdictLabel(verdictEvent.verdict)}</strong>
          </>
        ),
        rightText: pendingCount === 0 ? `No action needed · ${toggleText}` : `${pendingCount} licence${pendingCount === 1 ? "" : "s"} pending · ${toggleText}`,
        onClick: () => setDrawerOpen((v) => !v),
      };
    }
  }

  const availableTags = Array.from(new Set(messages.flatMap((m) => m.tags))).sort();
  const trimmedQuery = searchQuery.trim().toLowerCase();
  const visibleMessages = messages.filter((m) => {
    if (tagFilter && !m.tags.includes(tagFilter)) return false;
    if (!trimmedQuery) return true;
    const haystack = `${m.from.name ?? ""} ${m.from.address} ${m.subject ?? ""} ${m.snippet ?? ""}`.toLowerCase();
    return haystack.includes(trimmedQuery);
  });

  return (
    <main className="cockpit">
      <div className="mailpit-topbar">
        <span className="mailpit-topbar__brand">Mailpit</span>
        <input
          type="text"
          className="mailpit-topbar__search"
          placeholder="Search mailbox…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <span className="mailpit-topbar__spacer" />
        <span className="mailpit-topbar__actions">
          <span className="mailpit-topbar__tags" ref={tagsMenuRef}>
            <button type="button" onClick={() => setTagsMenuOpen((v) => !v)} aria-expanded={tagsMenuOpen}>
              Tags{tagFilter ? `: ${tagFilter}` : ""}
            </button>
            {tagsMenuOpen && (
              <div className="mailpit-topbar__tags-menu" role="menu">
                <button
                  type="button"
                  className={tagFilter === null ? "mailpit-topbar__tag--active" : ""}
                  onClick={() => {
                    setTagFilter(null);
                    setTagsMenuOpen(false);
                  }}
                >
                  All messages
                </button>
                {availableTags.length === 0 && <p className="mailpit-topbar__tags-empty">No tags yet.</p>}
                {availableTags.map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    className={tagFilter === tag ? "mailpit-topbar__tag--active" : ""}
                    onClick={() => {
                      setTagFilter(tag);
                      setTagsMenuOpen(false);
                    }}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            )}
          </span>
          <button type="button" onClick={onMarkAllRead} disabled={markingAllRead}>
            {markingAllRead ? "Marking…" : "Mark all read"}
          </button>
          <button type="button" onClick={onDeleteAll} disabled={deletingAll}>
            {deletingAll ? "Deleting…" : "Delete all"}
          </button>
        </span>
      </div>

      <p className="cockpit__status">
        <span className="cockpit__source">{sourceLabel}</span>
        {status === "error" && `Error: ${error}`}
        {decisionError && ` · licence decision failed: ${decisionError}`}
        {mailboxActionError && ` · ${mailboxActionError}`}
      </p>

      <div className="cockpit__layout">
        <Inbox messages={visibleMessages} selectedId={selectedId} onSelect={setSelectedId} investigatedId={investigatedId} />

        <ReadingPane message={selectedMessage} mailpitBaseUrl={mailpitBaseUrl} banner={banner} />

        {isInvestigatedSelection && drawerOpen && (verdictEvent || failedEvent) && (
          <MissionContextPanel
            key={selectedId}
            events={allEvents}
            missionId={messageEvent?.message.message_id ?? null}
            onDecision={liveMission ? onDecision : undefined}
            pendingGates={pendingGates}
            onDismiss={() => setDrawerOpen(false)}
          />
        )}
      </div>
    </main>
  );
}

export default App;
