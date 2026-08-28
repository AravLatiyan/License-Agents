---
name: triage-a-message
description: Triage a suspicious email using the available message evidence, identify the URLs and sender signals that need investigation, and produce a structured handoff for detonation and evidence gathering.
---

# Triage a Message

Use this skill when a suspicious email needs initial triage.

## Procedure

1. Start from the parsed message data. Do not invent missing headers, URLs, sender identities, or authentication results.
2. Identify:
   - sender and display name
   - Reply-To and Return-Path
   - authentication results
   - linked URLs
   - attachment names and hashes
3. Separate observed facts from conclusions.
4. Flag mismatches between display name, sender address, Reply-To, and Return-Path.
5. Identify links that require detonation.
6. Treat attachments as static evidence only. Never execute an attachment.
7. Hand the resulting evidence to the appropriate infrastructure, identity, and history analysis work.
8. Keep the output concise and structured so later skills can consume it.

## Safety

- Never render remote images from the message.
- Never execute attachments.
- Never claim a URL is safe merely because reputation data is absent.
- Do not invent evidence that is not present in the parsed message.