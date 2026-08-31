// cockpit/src/Inbox.tsx
//
// The primary context: an inbox, not a dashboard. One row per message, real
// Mailpit data where it's reachable (mailpitSource.ts), a select handler,
// nothing else - the security analysis lives in MissionContextPanel,
// triggered only by selecting a row, never shown by default.
import type { InboxMessage } from "./mailpitSource";

export function Inbox({
  messages,
  selectedId,
  onSelect,
  investigatedId,
}: {
  messages: InboxMessage[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** The one message this session's mission is actually about - the only
   *  row that currently opens a real investigation panel. Other rows are
   *  real Mailpit messages with no mission run for them yet (T-XXX, §8:
   *  triggering a fresh mission per arbitrary clicked message is real
   *  future work, not built here - see PLAN.md). */
  investigatedId: string | null;
}) {
  return (
    <section className="inbox" aria-label="Inbox">
      <p className="inbox__count">Inbox · {messages.length} message{messages.length === 1 ? "" : "s"}</p>
      {messages.length === 0 ? (
        <p className="inbox__empty">No messages.</p>
      ) : (
        <ul className="inbox__list">
          {messages.map((m) => (
            <InboxRow
              key={m.id}
              message={m}
              selected={m.id === selectedId}
              investigated={m.id === investigatedId}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function InboxRow({
  message,
  selected,
  investigated,
  onSelect,
}: {
  message: InboxMessage;
  selected: boolean;
  investigated: boolean;
  onSelect: (id: string) => void;
}) {
  const senderLabel = message.from.name ?? message.from.address;
  const hasFlags = message.tags.length > 0 || investigated;
  return (
    <li className={`inbox-row${selected ? " inbox-row--selected" : ""}${message.read ? "" : " inbox-row--unread"}`}>
      <button type="button" className="inbox-row__button" onClick={() => onSelect(message.id)} aria-pressed={selected}>
        <span className="inbox-row__top">
          <span className="inbox-row__sender">{senderLabel}</span>
          {message.date && <span className="inbox-row__time">{formatDate(message.date)}</span>}
        </span>
        <span className="inbox-row__subject">{message.subject ?? "(no subject)"}</span>
        {message.snippet && <span className="inbox-row__snippet">{message.snippet}</span>}
        {hasFlags && (
          <span className="inbox-row__meta">
            {message.tags.map((tag) => (
              <span key={tag} className="inbox-row__tag">
                {tag}
              </span>
            ))}
            {investigated && <span className="inbox-row__flag">Analysed</span>}
          </span>
        )}
      </button>
    </li>
  );
}

/** Best-effort local rendering of Mailpit's RFC3339Nano string. Falls back
 *  to the raw string rather than hiding a value that failed to parse. */
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
