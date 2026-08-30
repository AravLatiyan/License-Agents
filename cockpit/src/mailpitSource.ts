// cockpit/src/mailpitSource.ts
//
// The real inbox: Mailpit's own HTTP API (range/mailpit-api.json,
// GET /api/v1/messages), the same API tools/imports_mcp/quarantine.py and
// correspondence_history.py already talk to server-side (§6, 2026-08-29 —
// "Mailpit's HTTP API, no separate IMAP service"). Nothing new is invented
// here: this is that same existing contract, read client-side so the Cockpit
// can show the mailbox a message actually lives in, not just replay one
// mission's own event stream.
//
// Never throws. A judge's laptop with no Range running (T-065/rule 5's
// clean-clone guarantee) must still show a working Cockpit — so any fetch
// failure, non-ok status, or unexpected shape degrades to `null`, and the
// caller falls back to the one message it already knows about from the
// mission stream itself.

export interface InboxMessage {
  id: string;
  from: { name: string | null; address: string };
  subject: string | null;
  /** Created, as Mailpit's own RFC3339Nano string - rendered, never parsed
   *  into a different format (same "pass upstream date format through
   *  unmodified" decision tools/imports_mcp/correspondence_history.py made). */
  date: string | null;
  snippet: string | null;
  tags: string[];
  /** Mailpit's own read/unread flag - real data, not inferred, and only
   *  ever true for a synthetic (mailpitId === null) row since there's no
   *  real message to have a read state at all. */
  read: boolean;
  /** Mailpit's own row ID - the one the reading pane fetches by
   *  (fetchMailpitMessage/fetchMailpitHeaders/fetchMailpitRaw). Distinct from
   *  `id` above: App.tsx pins the investigated row's `id` to the mission's
   *  own message_id (§7, T-047) so React selection identity survives before
   *  a live Mailpit match arrives, but that pinned value was never a real
   *  Mailpit row and must never be used to fetch one. `null` means exactly
   *  that - a synthetic row built from the mission stream alone, with no
   *  backing message to read a body from. */
  mailpitId: string | null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
const isStr = (v: unknown): v is string => typeof v === "string";

/** Mailpit's Address struct - {Name, Address} - guarded the same way every
 *  other tool-result shape in this project is: proven, not assumed. */
function addressOf(v: unknown): { name: string | null; address: string } | null {
  if (!isRecord(v)) return null;
  const address = v.Address;
  if (!isStr(address)) return null;
  const name = v.Name;
  return { name: isStr(name) && name.length > 0 ? name : null, address };
}

function messageOf(v: unknown): InboxMessage | null {
  if (!isRecord(v)) return null;
  const id = v.ID;
  const from = addressOf(v.From);
  if (!isStr(id) || !from) return null;
  const subject = v.Subject;
  const created = v.Created;
  const snippet = v.Snippet;
  const tags = v.Tags;
  return {
    id,
    from,
    subject: isStr(subject) && subject.length > 0 ? subject : null,
    date: isStr(created) ? created : null,
    snippet: isStr(snippet) && snippet.length > 0 ? snippet : null,
    tags: Array.isArray(tags) ? tags.filter(isStr) : [],
    read: v.Read === true,
    mailpitId: id, // a real list row - always its own backing message
  };
}

/**
 * The mailbox's messages, newest first (Mailpit's own default order).
 * Returns `null` on anything that isn't a clean 200 with the expected shape
 * - never partial data presented as complete, and never an exception the
 * caller has to remember to catch.
 */
export async function fetchMailpitInbox(baseUrl: string, fetchImpl: typeof fetch = fetch): Promise<InboxMessage[] | null> {
  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/api/v1/messages`);
  } catch {
    return null; // no server reachable at all - the common case on a clean clone
  }
  if (!response.ok) return null;

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }
  if (!isRecord(body) || !Array.isArray(body.messages)) return null;

  const messages = body.messages.map(messageOf).filter((m): m is InboxMessage => m !== null);
  return messages;
}

/**
 * A single message's real content - what the reading pane renders. Mirrors
 * Mailpit's own `Message` schema (range/mailpit-api.json's `definitions.
 * Message`) exactly: `From`/`To`/`ReplyTo` are `Address` objects/arrays,
 * `HTML`/`Text` are the two body renderings Mailpit itself already parsed
 * out of the MIME structure - never re-parsed here.
 */
export interface MailpitMessageDetail {
  id: string;
  subject: string | null;
  from: { name: string | null; address: string } | null;
  to: Array<{ name: string | null; address: string }>;
  replyTo: Array<{ name: string | null; address: string }>;
  date: string | null;
  html: string | null;
  text: string | null;
}

function detailOf(v: unknown): MailpitMessageDetail | null {
  if (!isRecord(v)) return null;
  const id = v.ID;
  if (!isStr(id)) return null;
  const subject = v.Subject;
  const date = v.Date;
  const html = v.HTML;
  const text = v.Text;
  const to = Array.isArray(v.To) ? v.To.map(addressOf).filter((a): a is { name: string | null; address: string } => a !== null) : [];
  const replyTo = Array.isArray(v.ReplyTo)
    ? v.ReplyTo.map(addressOf).filter((a): a is { name: string | null; address: string } => a !== null)
    : [];
  return {
    id,
    subject: isStr(subject) && subject.length > 0 ? subject : null,
    from: addressOf(v.From),
    to,
    replyTo,
    date: isStr(date) ? date : null,
    html: isStr(html) && html.length > 0 ? html : null,
    text: isStr(text) && text.length > 0 ? text : null,
  };
}

/** `GET /api/v1/message/{ID}` - the reading pane's HTML/Text tabs and its
 *  From/Reply-To/To header grid. Same never-throws contract as
 *  fetchMailpitInbox: a judge's laptop with nothing running still shows a
 *  working reading pane (an honest "not available" state), not a crash. */
export async function fetchMailpitMessage(
  baseUrl: string,
  id: string,
  fetchImpl: typeof fetch = fetch,
): Promise<MailpitMessageDetail | null> {
  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/api/v1/message/${encodeURIComponent(id)}`);
  } catch {
    return null;
  }
  if (!response.ok) return null;
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }
  return detailOf(body);
}

/** `GET /api/v1/message/{ID}/headers` - the reading pane's Headers tab.
 *  The real shape (range/mailpit-api.json's `MessageHeadersResponse`) is a
 *  map of header name to its raw string values, already split by Mailpit -
 *  rendered as-is, never reformatted. */
export async function fetchMailpitHeaders(
  baseUrl: string,
  id: string,
  fetchImpl: typeof fetch = fetch,
): Promise<Record<string, string[]> | null> {
  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/api/v1/message/${encodeURIComponent(id)}/headers`);
  } catch {
    return null;
  }
  if (!response.ok) return null;
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }
  if (!isRecord(body)) return null;
  const out: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(body)) {
    if (Array.isArray(value)) out[key] = value.filter(isStr);
  }
  return out;
}

/** `GET /api/v1/message/{ID}/raw` - the reading pane's Source tab. Mailpit's
 *  `TextResponse` is a plain string body, not JSON - read as text, not
 *  parsed. Fetched lazily (only once the Source tab is actually opened,
 *  ReadingPane.tsx) since a raw .eml can be considerably larger than the
 *  parsed HTML/Text this component fetches eagerly. */
/** `PUT /api/v1/messages` with no `IDs`/`Search` - Mailpit's own documented
 *  meaning is "apply to every message in the mailbox" (range/mailpit-api.json,
 *  `SetReadStatusParams`). The mailbox-level "Mark all read" control.
 *  Returns whether it actually succeeded so the caller can decide whether a
 *  re-fetch is worth doing - never throws, same contract as every other
 *  function in this file. */
/** `{ok: true}` or `{ok: false, detail}` - richer than a plain boolean on
 *  purpose. A network-level exception (server unreachable, CORS block) and
 *  a real non-2xx HTTP response used to collapse to the same bare `false`,
 *  which is exactly what made an earlier version of this failure
 *  undiagnosable from the UI alone - `detail` is what a human actually
 *  needs to tell those apart. */
export type MailboxActionResult = { ok: true } | { ok: false; detail: string };

export async function markAllRead(baseUrl: string, fetchImpl: typeof fetch = fetch): Promise<MailboxActionResult> {
  try {
    const response = await fetchImpl(`${baseUrl}/api/v1/messages`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ Read: true }),
    });
    if (response.ok) return { ok: true };
    const body = await response.text().catch(() => "");
    return { ok: false, detail: `HTTP ${response.status}${body ? `: ${body.slice(0, 200)}` : ""}` };
  } catch (err) {
    return { ok: false, detail: err instanceof Error ? err.message : String(err) };
  }
}

/** `DELETE /api/v1/messages` with no `IDs` - Mailpit's own documented
 *  meaning is "delete every message in the mailbox" (same doc,
 *  `DeleteMessagesParams`: "If no IDs are provided then all messages are
 *  deleted"). Irreversible - the caller (App.tsx's "Delete all") is
 *  expected to confirm with the user before calling this, the same way any
 *  other destructive, hard-to-reverse action in this app would. */
export async function deleteAllMessages(baseUrl: string, fetchImpl: typeof fetch = fetch): Promise<MailboxActionResult> {
  try {
    const response = await fetchImpl(`${baseUrl}/api/v1/messages`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (response.ok) return { ok: true };
    const body = await response.text().catch(() => "");
    return { ok: false, detail: `HTTP ${response.status}${body ? `: ${body.slice(0, 200)}` : ""}` };
  } catch (err) {
    return { ok: false, detail: err instanceof Error ? err.message : String(err) };
  }
}

export async function fetchMailpitRaw(baseUrl: string, id: string, fetchImpl: typeof fetch = fetch): Promise<string | null> {
  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/api/v1/message/${encodeURIComponent(id)}/raw`);
  } catch {
    return null;
  }
  if (!response.ok) return null;
  try {
    return await response.text();
  } catch {
    return null;
  }
}
