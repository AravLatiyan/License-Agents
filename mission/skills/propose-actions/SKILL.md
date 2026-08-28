---
name: propose-actions
description: Turn established email-fraud evidence into the appropriate reversible or external actions, clearly stating what each action would do and waiting for human approval.
---

# Propose Actions

Use this skill after the evidence and verdict are established.

## Available Actions

The project defines four state-changing actions:

- quarantine the message
- notify the impersonated party
- create a block rule
- file an abuse report

## Procedure

1. Base every proposed action on evidence already gathered.
2. Explain why the action is appropriate.
3. State the target and expected effect when the available tool schema provides those fields.
4. Propose actions individually rather than bundling unrelated actions together.
5. Never assume approval.
6. Wait for the human approval gate before executing any state-changing action.
7. If evidence is insufficient, say so instead of inventing a justification.

## Safety

Actions that change state outside the sandbox require explicit human approval.

Never:
- silently execute an action,
- claim an action succeeded before its tool result confirms success,
- fabricate an abuse contact or recipient,
- send a real abuse report during Range testing.