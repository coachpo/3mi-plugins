# Claude Code adapter

Read this adapter only when the current host is Claude Code.

Delegate a frozen lane to the built-in `Explore` subagent only when its actual
tool surface mechanically permits repository reads while excluding writes,
network access, and further delegation. Do not infer this guarantee from the
agent name or prompt; use the sequential fallback when it is unavailable.

For an eligible delegated lane:

- request `model: haiku`;
- select per-lane `searchDepth` from `quick`, `medium`, or `very thorough`;
- repeat the complete frozen worker input contract in the Explore prompt;
- batch already frozen lanes when capacity is limited.

`searchDepth` controls search work and is not a reasoning-effort setting. In
`execution`, use `adapter: claude-code`, `workerModel: haiku`,
`reasoning_effort: not-applicable`, and `searchDepth: <selected-value>`. For the
sequential fallback, set both host controls and `workerModel` to `not-applicable`
and record the exact `fallbackReason`.
