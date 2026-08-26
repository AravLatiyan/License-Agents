import { parse as parseHtml } from "node-html-parser";
import dns from "node:dns/promises";
import net from "node:net";

const MAX_REDIRECT_HOPS = 10;
const REQUEST_TIMEOUT_MS = 5000;
const MAX_BODY_BYTES = 2 * 1024 * 1024; // bound attacker-controlled response size before buffering/parsing

/**
 * Text-mode detonation: follow redirects, parse the final HTML with a real
 * parser (never regex), and flag forms that ask for a password and post to
 * a different origin than the page they're on. No screenshot — that's the
 * chromium-in-Daytona path, unconfirmed (§6, 2026-08-25).
 *
 * Every failure mode (bad URL, DNS/connection failure, timeout, malformed
 * redirect location, oversized body) returns the same {url, redirect_chain,
 * error} shape instead of throwing — the target is untrusted and frequently
 * unreachable, and a dead phishing URL is a routine result, not a crash.
 *
 * SSRF guard (Rule 2880752): the initial URL and every redirect hop are
 * refused if they resolve to a loopback/RFC1918/link-local/cloud-metadata
 * address, so an attacker-controlled page can't use this fetcher to probe
 * internal services. `allowPrivateNetworkTargets` exists only for the local
 * unit-test fixture (detonate.test.js) to opt back in explicitly — never set
 * it for a real detonation.
 */
export async function detonate(
  startUrl,
  { timeoutMs = REQUEST_TIMEOUT_MS, maxBodyBytes = MAX_BODY_BYTES, allowPrivateNetworkTargets = false } = {}
) {
  const redirectChain = [];
  let currentUrl = startUrl;

  try {
    for (let hop = 0; hop <= MAX_REDIRECT_HOPS; hop++) {
      if (hop === MAX_REDIRECT_HOPS) {
        return {
          url: startUrl,
          redirect_chain: redirectChain,
          error: `redirect chain exceeded ${MAX_REDIRECT_HOPS} hops`,
        };
      }

      const parsed = new URL(currentUrl);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return {
          url: startUrl,
          redirect_chain: redirectChain,
          error: `refused non-http(s) scheme: ${parsed.protocol}`,
        };
      }

      if (!allowPrivateNetworkTargets) {
        const privateTarget = await resolvesToPrivateNetwork(parsed.hostname);
        if (privateTarget) {
          return {
            url: startUrl,
            redirect_chain: redirectChain,
            error: `refused private/internal network target: ${parsed.hostname} resolves to ${privateTarget}`,
          };
        }
      }

      const response = await fetch(currentUrl, {
        redirect: "manual",
        signal: AbortSignal.timeout(timeoutMs),
      });

      redirectChain.push({ url: currentUrl, status: response.status });

      const location = response.headers.get("location");
      if (response.status >= 300 && response.status < 400 && location) {
        currentUrl = new URL(location, currentUrl).toString();
        continue;
      }

      const finalUrl = currentUrl;
      const contentType = (response.headers.get("content-type") ?? "").toLowerCase();
      const isHtml = contentType.includes("html");

      const { text: body, tooLarge } = await readBodyWithLimit(response, maxBodyBytes);
      if (tooLarge) {
        return {
          url: startUrl,
          redirect_chain: redirectChain,
          error: `response body exceeded ${maxBodyBytes} byte limit`,
        };
      }

      if (!isHtml) {
        return {
          url: startUrl,
          redirect_chain: redirectChain,
          final_url: finalUrl,
          forms: [],
          summary: `Final response is not HTML (content-type: ${contentType || "unknown"}); no forms to analyze.`,
        };
      }

      const forms = extractForms(body, finalUrl);
      const suspicious = forms.find((f) => f.asks_password && f.cross_domain);

      return {
        url: startUrl,
        redirect_chain: redirectChain,
        final_url: finalUrl,
        forms,
        summary: suspicious
          ? `This page asks for a password and posts it to ${suspicious.action_origin}, a different domain than ${new URL(finalUrl).origin}.`
          : "No form on the final page asks for a password and posts cross-domain.",
      };
    }
  } catch (err) {
    return { url: startUrl, redirect_chain: redirectChain, error: describeError(err) };
  }
}

// IPv4 ranges that must never be reachable from this fetcher: loopback,
// RFC1918 private space, link-local (which is also where cloud metadata
// endpoints like 169.254.169.254 live), and the unspecified/"this network" block.
const PRIVATE_IPV4_RANGES = [
  /^127\./,
  /^10\./,
  /^172\.(1[6-9]|2\d|3[01])\./,
  /^192\.168\./,
  /^169\.254\./,
  /^0\./,
];

function isPrivateIPv4(address) {
  return PRIVATE_IPV4_RANGES.some((range) => range.test(address));
}

function isPrivateIPv6(address) {
  const lower = address.toLowerCase();
  return lower === "::1" || lower === "::" || lower.startsWith("fc") || lower.startsWith("fd") || lower.startsWith("fe80");
}

// Checks the *resolved* address, not just the hostname string, so a domain
// name that resolves to an internal IP (DNS rebinding) is caught too, not
// only literal http://127.0.0.1 style URLs.
async function resolvesToPrivateNetwork(hostname) {
  const literalFamily = net.isIP(hostname);
  const addresses = literalFamily
    ? [{ address: hostname, family: literalFamily }]
    : await dns.lookup(hostname, { all: true });

  for (const { address, family } of addresses) {
    if (family === 6 ? isPrivateIPv6(address) : isPrivateIPv4(address)) {
      return address;
    }
  }
  return null;
}

function describeError(err) {
  const cause = err?.cause?.message ? ` (${err.cause.message})` : "";
  return `${err?.name ?? "Error"}: ${err?.message ?? String(err)}${cause}`;
}

// Streams the body with a hard byte cap instead of response.text(), which
// buffers unbounded — an attacker-controlled server can otherwise exhaust
// memory with a fast, oversized response regardless of the request timeout.
async function readBodyWithLimit(response, maxBytes) {
  const reader = response.body?.getReader();
  if (!reader) {
    return { text: "", tooLarge: false };
  }

  const decoder = new TextDecoder();
  let text = "";
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      return { text: "", tooLarge: true };
    }
    text += decoder.decode(value, { stream: true });
  }
  text += decoder.decode();
  return { text, tooLarge: false };
}

// Untrusted HTML: one malformed form action must not prevent every other
// form on the page from being reported.
function extractForms(html, pageUrl) {
  const root = parseHtml(html);
  const pageOrigin = new URL(pageUrl).origin;
  const forms = [];

  for (const form of root.querySelectorAll("form")) {
    const rawAction = form.getAttribute("action") ?? "";
    const method = (form.getAttribute("method") ?? "GET").toUpperCase();
    const asksPassword = form.querySelector('input[type="password"]') !== null;

    try {
      const actionUrl = new URL(rawAction || pageUrl, pageUrl);
      forms.push({
        action: actionUrl.toString(),
        action_origin: actionUrl.origin,
        method,
        cross_domain: actionUrl.origin !== pageOrigin,
        asks_password: asksPassword,
      });
    } catch {
      forms.push({
        action: rawAction,
        action_origin: null,
        method,
        cross_domain: null,
        asks_password: asksPassword,
        action_invalid: true,
      });
    }
  }

  return forms;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const url = process.argv[2];
  if (!url) {
    console.error("usage: node detonate.js <url>");
    process.exit(1);
  }
  const result = await detonate(url);
  console.log(JSON.stringify(result, null, 2));
}
