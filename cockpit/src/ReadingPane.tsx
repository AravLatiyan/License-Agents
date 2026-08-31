// cockpit/src/ReadingPane.tsx
//
// Mailpit's own reading pane, re-created around its real message-detail API
// (fetchMailpitMessage/fetchMailpitHeaders/fetchMailpitRaw, mailpitSource.ts)
// rather than Cockpit's own event stream - this is what makes Mailpit the
// actual frontend instead of a data source for a bespoke one. The
// investigation banner is the only injected element; everything below it
// (subject, From/Reply-To/To, HTML/Text/Source/Headers tabs, the body
// itself) is real Mailpit content, honest about being unavailable when
// there's no live match (mailpitId === null) or Mailpit isn't reachable.
import { useEffect, useState, type ReactNode } from "react";
import {
  fetchMailpitHeaders,
  fetchMailpitMessage,
  fetchMailpitRaw,
  type InboxMessage,
  type MailpitMessageDetail,
} from "./mailpitSource";

type Tab = "html" | "text" | "source" | "headers";

export interface InvestigationBanner {
  /** Drives only the left border color - App.tsx owns the actual wording
   *  (leftText below), since a failed/cancelled mission needs real text
   *  ("Investigation failed: <cause>") that no fixed label set covers. */
  status: "investigating" | "malicious" | "suspicious" | "legitimate";
  leftText: ReactNode;
  /** Right-aligned text. Clickable (opens/closes the drawer) when
   *  `onClick` is given - omitted mid-investigation, when there's no
   *  drawer yet to open. */
  rightText: string;
  onClick?: () => void;
}

export function ReadingPane({
  message,
  mailpitBaseUrl,
  banner,
}: {
  message: InboxMessage | null;
  mailpitBaseUrl: string;
  banner: InvestigationBanner | null;
}) {
  const mailpitId = message?.mailpitId ?? null;

  // `undefined` means "still in flight"; `null` means "the request finished
  // and failed". The source helpers deliberately return null for every
  // failure mode, so collapsing both into one sentinel left a failed HTML,
  // Text or Headers fetch rendering "Loading..." forever (Qodo, PR #100
  // finding #3).
  const [detail, setDetail] = useState<MailpitMessageDetail | null | undefined>(undefined);
  const [headers, setHeaders] = useState<Record<string, string[]> | null | undefined>(undefined);
  const [tab, setTab] = useState<Tab>("html");
  const [raw, setRaw] = useState<string | null>(null);

  // A fresh selection means fresh content - stale HTML from the previous
  // message must never flash under a message that hasn't loaded yet.
  useEffect(() => {
    setDetail(undefined);
    setHeaders(undefined);
    setRaw(null);
    setTab("html");
    if (!mailpitId) return;
    let cancelled = false;
    void fetchMailpitMessage(mailpitBaseUrl, mailpitId).then((d) => {
      if (!cancelled) setDetail(d);
    });
    void fetchMailpitHeaders(mailpitBaseUrl, mailpitId).then((h) => {
      if (!cancelled) setHeaders(h);
    });
    return () => {
      cancelled = true;
    };
  }, [mailpitId, mailpitBaseUrl]);

  // The raw .eml can be considerably larger than the parsed HTML/Text this
  // effect fetches eagerly above - loaded only once the Source tab is
  // actually opened, and only once per message (raw === null guards a
  // re-fetch on every tab click back to Source).
  useEffect(() => {
    if (tab !== "source" || raw !== null || !mailpitId) return;
    let cancelled = false;
    void fetchMailpitRaw(mailpitBaseUrl, mailpitId).then((r) => {
      if (!cancelled) setRaw(r ?? "");
    });
    return () => {
      cancelled = true;
    };
  }, [tab, mailpitId, raw, mailpitBaseUrl]);

  if (!message) {
    return (
      <div className="reading-pane reading-pane--empty" aria-hidden="true">
        Select a message to read it
      </div>
    );
  }

  const senderLabel = message.from.name ?? message.from.address;
  const subject = detail?.subject ?? message.subject ?? "(no subject)";

  return (
    <div className="reading-pane">
      {banner && <BannerRow banner={banner} />}

      <div className="reading-pane__header">
        <h2 className="reading-pane__subject">{subject}</h2>
        <div className="reading-pane__fields">
          <span className="reading-pane__field-label">From</span>
          <span>
            {senderLabel} <span className="reading-pane__addr">&lt;{message.from.address}&gt;</span>
          </span>
          {detail && detail.replyTo.length > 0 && (
            <>
              <span className="reading-pane__field-label">Reply-To</span>
              <span className="reading-pane__addr">{detail.replyTo.map((a) => a.address).join(", ")}</span>
            </>
          )}
          {detail && detail.to.length > 0 && (
            <>
              <span className="reading-pane__field-label">To</span>
              <span className="reading-pane__addr">{detail.to.map((a) => a.address).join(", ")}</span>
            </>
          )}
        </div>
        <div className="reading-pane__tabs" role="tablist">
          {(["html", "text", "source", "headers"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              className={`reading-pane__tab${tab === t ? " reading-pane__tab--active" : ""}`}
              onClick={() => setTab(t)}
            >
              {t === "html" ? "HTML" : t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
          <span className="reading-pane__tabs-spacer" />
          <span className="reading-pane__meta">
            {message.id}
            {message.date && ` · ${formatDate(message.date)}`}
          </span>
        </div>
      </div>

      <div className="reading-pane__body">
        {!mailpitId ? (
          <p className="reading-pane__unavailable">No live Mailpit match for this message - nothing to read here yet.</p>
        ) : (
          <TabContent tab={tab} detail={detail} headers={headers} raw={raw} />
        )}
      </div>
    </div>
  );
}

function TabContent({
  tab,
  detail,
  headers,
  raw,
}: {
  tab: Tab;
  detail: MailpitMessageDetail | null | undefined;
  headers: Record<string, string[]> | null | undefined;
  raw: string | null;
}) {
  if (tab === "html") {
    if (detail === undefined) return <p className="reading-pane__unavailable">Loading…</p>;
    if (detail === null) return <p className="reading-pane__unavailable">Message content could not be loaded.</p>;
    if (!detail.html) return <p className="reading-pane__unavailable">No HTML body.</p>;
    // Untrusted email HTML - a real Mailpit renders this in a sandboxed
    // frame for the same reason: it must never run script or read this
    // page's own origin, whatever a phishing fixture's body contains.
    return <iframe title="Message body (HTML)" sandbox="" srcDoc={detail.html} className="reading-pane__iframe" />;
  }
  if (tab === "text") {
    if (detail === undefined) return <p className="reading-pane__unavailable">Loading…</p>;
    if (detail === null) return <p className="reading-pane__unavailable">Message content could not be loaded.</p>;
    if (!detail.text) return <p className="reading-pane__unavailable">No text body.</p>;
    return <pre className="reading-pane__pre">{detail.text}</pre>;
  }
  if (tab === "source") {
    if (raw === null) return <p className="reading-pane__unavailable">Loading…</p>;
    if (raw === "") return <p className="reading-pane__unavailable">Source not available.</p>;
    return <pre className="reading-pane__pre">{raw}</pre>;
  }
  // headers
  if (headers === undefined) return <p className="reading-pane__unavailable">Loading…</p>;
  if (headers === null) return <p className="reading-pane__unavailable">Headers could not be loaded.</p>;
  const entries = Object.entries(headers);
  if (entries.length === 0) return <p className="reading-pane__unavailable">Headers not available.</p>;
  return (
    <dl className="reading-pane__headers">
      {entries.map(([name, values]) => (
        <div key={name} className="reading-pane__header-row">
          <dt>{name}</dt>
          <dd>{values.join(", ")}</dd>
        </div>
      ))}
    </dl>
  );
}

function BannerRow({ banner }: { banner: InvestigationBanner }) {
  return (
    <div className={`reading-pane__banner reading-pane__banner--${banner.status}`}>
      <span>{banner.leftText}</span>
      <span className="reading-pane__banner-spacer" />
      {banner.onClick ? (
        <button type="button" className="reading-pane__banner-action" onClick={banner.onClick}>
          {banner.rightText}
        </button>
      ) : (
        <span className="reading-pane__banner-meta">{banner.rightText}</span>
      )}
    </div>
  );
}

/** Best-effort local rendering of Mailpit's RFC3339Nano string - same
 *  fallback-to-raw-string pattern as Inbox.tsx's own formatDate. */
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
