/**
 * T-056: reconnect handling - TrueForge survives reconnects, so the UI
 * should. The confirmed mechanic (T-002/§6) is `GET /turns/{id}/subscribe
 * ?after_sequence_number=N`: a dropped stream reconnects by replaying from
 * the last sequence number seen, not from the start.
 *
 * This module is transport-agnostic on purpose. Building the actual live
 * `trueForgeEventSource` (missionSource.ts's own docstring names it as the
 * next swap-in) needs more than reconnect logic - it needs a translation
 * layer from TrueForge's raw turn-stream events into this app's `mission.*`
 * events, and nothing in PLAN.md/contracts/ has ever defined that mapping
 * (§10 names the mission.* stages; T-002 only confirmed the generic
 * session/turn/tool-approval mechanics, not how a lead agent's activity
 * becomes a mission.evidence/mission.detonation event). Inventing that
 * mapping here would be exactly the kind of undocumented-API guess CLAUDE.md
 * warns against - logged in PLAN.md §7/§8, not solved in this file.
 *
 * What *is* fully confirmed and independently valuable: the resume-by-
 * sequence-number mechanic itself. `resumableStream` implements and tests
 * that in isolation - reconnect, resume from the right offset, no dropped
 * or duplicated events, connection status exposed - against any pluggable
 * "open a stream starting at sequence N" function, ready for the real
 * trueForceEventSource to use once the translation layer exists.
 */

export type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "closed" | "error";

/** One item off the wire, tagged with the sequence number that would be
 *  passed as `after_sequence_number` to resume just past it. */
export interface SequencedItem<T> {
  sequenceNumber: number;
  value: T;
}

export interface ResumableStreamOptions<T> {
  /**
   * Opens one connection attempt, starting just after `afterSequenceNumber`
   * (null on the very first attempt - no resume point yet). Must yield
   * items in increasing sequence order and end (return, or throw on a
   * genuine drop) when the connection closes - `resumableStream` handles
   * turning "it ended" into "reconnect from here," this callback doesn't.
   */
  connect: (afterSequenceNumber: number | null) => AsyncIterable<SequencedItem<T>>;
  onStatusChange?: (status: ConnectionStatus) => void;
  /** Reconnect attempts after the first successful connection drops. `0`
   *  means "don't reconnect at all" - still useful for tests. */
  maxReconnectAttempts?: number;
  /** Base delay before a reconnect attempt; doubles each attempt (capped),
   *  so a flapping connection doesn't hammer the endpoint. */
  retryDelayMs?: number;
  maxRetryDelayMs?: number;
}

const DEFAULT_MAX_RECONNECT_ATTEMPTS = 5;
const DEFAULT_RETRY_DELAY_MS = 500;
const DEFAULT_MAX_RETRY_DELAY_MS = 8000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Consumes `connect` as one continuous stream: on a drop, waits with
 * exponential backoff and reconnects passing the last sequence number
 * actually yielded, so the resumed connection picks up exactly where the
 * dropped one left off - not from the start, not skipping anything. An
 * item whose sequence number is `<=` the last one already yielded is
 * dropped (defends against a resume boundary that re-sends its last item,
 * a well-known SSE resume edge case, without needing the server to promise
 * strict exclusivity).
 */
export async function* resumableStream<T>(options: ResumableStreamOptions<T>): AsyncGenerator<T> {
  const maxAttempts = options.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECT_ATTEMPTS;
  const baseDelay = options.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
  const maxDelay = options.maxRetryDelayMs ?? DEFAULT_MAX_RETRY_DELAY_MS;

  let lastSequenceNumber: number | null = null;
  let attempt = 0;
  const setStatus = (status: ConnectionStatus) => options.onStatusChange?.(status);

  setStatus("connecting");
  for (;;) {
    try {
      for await (const item of options.connect(lastSequenceNumber)) {
        if (lastSequenceNumber !== null && item.sequenceNumber <= lastSequenceNumber) {
          continue; // already yielded, a resume-boundary duplicate
        }
        lastSequenceNumber = item.sequenceNumber;
        attempt = 0; // a successfully-processed item resets the backoff
        setStatus("connected");
        yield item.value;
      }
      // connect() ended without throwing: the stream finished cleanly
      // (e.g. the turn completed), not a drop - nothing to reconnect to.
      setStatus("closed");
      return;
    } catch (err) {
      attempt += 1;
      if (attempt > maxAttempts) {
        setStatus("error");
        throw err instanceof Error ? err : new Error(String(err));
      }
      setStatus("reconnecting");
      const delay = Math.min(baseDelay * 2 ** (attempt - 1), maxDelay);
      await sleep(delay);
    }
  }
}
