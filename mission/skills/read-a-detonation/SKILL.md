---
name: read-a-detonation
description: Interpret a detonation result by summarizing redirects, the final page, forms, password requests, and cross-origin form targets without exposing raw HTML.
---

# Read a Detonation

Use this skill when a sandbox detonation result is available.

## Procedure

1. Read the structured detonation result.
2. Summarize the redirect chain in order.
3. Identify the final URL.
4. Determine whether the final page contains a form.
5. Determine whether the form asks for a password.
6. Determine whether the form submits to a different origin.
7. Record errors as evidence rather than treating an unreachable target as proof of safety.
8. Return concise structured findings suitable for the final verdict.

## Rules

- Do not reproduce raw HTML.
- Do not infer content that is absent from the detonation result.
- A failed or unreachable detonation is not evidence that the message is benign.
- Treat a password-collection form or cross-origin submission as a high-signal finding when the structured result reports it.