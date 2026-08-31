# Codex adapter

Read this adapter only when the current host is Codex.

Delegate a frozen lane only when the current runtime provides a worker sandbox or
tool profile that mechanically exposes repository reads and read-only Git while
disabling writes and network access. Standard prompt restrictions or a writable
workspace sandbox are insufficient; use the sequential fallback when this tool
surface is unavailable.

For an eligible delegated lane:

- spawn model `gpt-5.6-luna`;
- set `fork_turns` to `"none"` because the frozen prompt is self-contained;
- select per-lane `reasoning_effort` from `low`, `medium`, `high`, `xhigh`, or
  `max` according to ambiguity and search depth;
- batch already frozen lanes when capacity is limited.

In `execution`, use `adapter: codex`, the requested model,
`reasoning_effort: <selected-value>`, and `searchDepth: not-applicable`. For the
sequential fallback, use `workerModel: not-applicable`,
`reasoning_effort: not-applicable`, and record the exact `fallbackReason`.
