# Codex adapter

Read this adapter only when the current host is Codex.

Delegate a lane only when the current runtime provides a worker sandbox or tool
profile that mechanically exposes repository reads and read-only Git while
disabling writes and network access. Standard prompt restrictions or a writable
workspace sandbox are insufficient; use the sequential fallback when this tool
surface is unavailable.

For an eligible delegated lane:

- spawn model `gpt-5.6-luna`;
- set `fork_turns` to `"none"` because the prompt is self-contained;
- select per-lane `reasoning_effort` from `low`, `medium`, `high`, `xhigh`, or
  `max` according to ambiguity and search depth;
- batch lanes together when worker capacity is limited.

When the sequential fallback applies, note the reason in the final answer only
if it materially limited coverage.
