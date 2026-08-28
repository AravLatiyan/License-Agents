\# UNIVERSAL IMPORTS — TrueForge Write-up



\## 1. What the agent does



UNIVERSAL IMPORTS is an email counter-intelligence agent for investigating suspicious email.



The intended flow is:



1\. Parse the suspicious message and collect its existing evidence.

2\. Delegate investigation into three parallel lanes:

&#x20;  - \*\*INFRASTRUCTURE\*\* — domain, URL reputation, and sandbox detonation evidence.

&#x20;  - \*\*IDENTITY\*\* — sender identity, display name, Reply-To, Return-Path, and lookalike-domain analysis.

&#x20;  - \*\*HISTORY\*\* — prior correspondence with the sender and domain.

3\. Collect structured evidence from the three lanes.

4\. Produce a short plain-English verdict.

5\. When a state-changing action is warranted, call the corresponding gated tool.

6\. Let TrueForge pause the tool call for a human licence decision before the action can proceed.



The design deliberately keeps the harness responsible for platform capabilities such as sandbox lifecycle, subagent delegation, session handling, skill loading, and approval gates rather than reimplementing them in application code.



\## 2. TrueForge agent runtime



The agent is defined by `harness/agent.json`.



The manifest configures the `universal-imports` agent with the `anthropic/claude-sonnet-5` model, temperature `0.2`, and a maximum output of `4096` tokens.



The agent instructions define the investigation workflow, evidence boundaries between subagents, structured reporting requirements, and the rule that state-changing tools should be called directly so the native TrueForge approval gate can intercept them.



The repository treats these instructions as model guidance. They do not replace platform enforcement where the TrueForge configuration does not provide such enforcement.



\## 3. MCP tool integration



The agent references the `imports-mcp` connector.



The current read-only tool surface includes:



\- `parse\_message`

\- `domain\_intel`

\- `url\_reputation`



`parse\_message` provides parsed message evidence such as headers, authentication results, URLs, and attachment hashes.



`domain\_intel` provides domain-registration and certificate evidence.



`url\_reputation` provides URLhaus reputation information.



The agent instructions assign these tools to the infrastructure investigation lane.



\## 4. Dynamic subagents



`dynamic\_sub\_agents.enabled` is set to `true`.



The agent instructions request exactly three parallel investigation lanes:



\- INFRASTRUCTURE

\- IDENTITY

\- HISTORY



Each lane has a defined remit. The infrastructure lane handles infrastructure and detonation tools, identity works from parsed message fields, and history handles prior correspondence.



The reports are required to be structured evidence rather than prose. The lead agent then uses those reports to produce the final verdict.



An important implementation boundary is that the current TrueForge dynamic-subagent configuration does not enforce named subagents or per-subagent tool restrictions. The requested names, remits, parallelism, and reporting format are therefore model instructions rather than platform-enforced boundaries.



Runtime delegation and structured-report behavior have not yet been observed in this project environment, so this write-up does not claim those behaviors have been live-verified.



\## 5. Sandbox execution



The agent manifest enables the sandbox and disables file downloads:



```json

"sandbox": {

&#x20; "enabled": true,

&#x20; "file\_downloads": false

}
