import { parse as parseHtml } from "node-html-parser";

const MAX_REDIRECT_HOPS = 10;
const REQUEST_TIMEOUT_MS = 5000;

/**
 * Text-mode detonation: follow redirects, parse the final HTML with a real
 * parser (never regex), and flag forms that ask for a password and post to
 * a different origin than the page they're on. No screenshot — that's the
 * chromium-in-Daytona path, unconfirmed (§6, 2026-08-25).
 */
export async function detonate(startUrl) {
  const redirectChain = [];
  let currentUrl = startUrl;

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

    const response = await fetch(currentUrl, {
      redirect: "manual",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    redirectChain.push({ url: currentUrl, status: response.status });

    const location = response.headers.get("location");
    if (response.status >= 300 && response.status < 400 && location) {
      currentUrl = new URL(location, currentUrl).toString();
      continue;
    }

    const finalUrl = currentUrl;
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("html")) {
      return { url: startUrl, redirect_chain: redirectChain, final_url: finalUrl, forms: [] };
    }

    const body = await response.text();
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
}

function extractForms(html, pageUrl) {
  const root = parseHtml(html);
  const pageOrigin = new URL(pageUrl).origin;

  return root.querySelectorAll("form").map((form) => {
    const rawAction = form.getAttribute("action") ?? "";
    const actionUrl = new URL(rawAction || pageUrl, pageUrl);
    const asksPassword = form.querySelector('input[type="password"]') !== null;

    return {
      action: actionUrl.toString(),
      action_origin: actionUrl.origin,
      method: (form.getAttribute("method") ?? "GET").toUpperCase(),
      cross_domain: actionUrl.origin !== pageOrigin,
      asks_password: asksPassword,
    };
  });
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
