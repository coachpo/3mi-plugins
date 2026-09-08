# Claude Code adapter

Read this adapter only when the current host is Claude Code.

For ordinary read-only research, delegate independent lanes to the built-in
`Explore` subagent when current tool permissions and task authorization allow it.
Apply the shared skill's scoped read-only constraints, including no writes,
project-code execution, network access, or further delegation.

When applicable instructions explicitly require mechanical isolation, verify
that the actual tool surface permits repository reads while excluding writes,
network access, and further delegation; otherwise use the sequential fallback.
Do not infer mechanical isolation from the agent name or prompt, or use prompt
constraints to override runtime permissions.

For an eligible delegated lane:

- request `model: haiku`;
- select per-lane `searchDepth` from `quick`, `medium`, or `very thorough`;
- repeat the complete worker input contract in the Explore prompt;
- batch lanes together when worker capacity is limited.

`searchDepth` controls search work, not reasoning effort. Disclose missing
isolation capabilities when they affect the user's requirements; otherwise
mention a sequential fallback only when it materially limited coverage.
