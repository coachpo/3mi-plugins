# Codex adapter

Read this adapter only when the current host is Codex.

For ordinary read-only research, delegate independent lanes when current tool
permissions and task authorization allow it, even without a dedicated read-only
sandbox. Give each worker a self-contained prompt limiting reads to the assigned
scope and prohibiting writes, project-code execution, network access, and further
delegation, as required by the shared skill.

When applicable instructions explicitly require mechanical isolation, use a
worker sandbox or tool profile that permits repository reads and read-only Git
while disabling writes and network access; otherwise use the sequential fallback.
Prompt constraints or a writable workspace sandbox do not establish that
guarantee and cannot override runtime permissions.

For an eligible delegated lane:

- spawn model `gpt-5.6-luna`;
- set `fork_turns` to `"none"` because the prompt is self-contained;
- select per-lane `reasoning_effort` from `low`, `medium`, `high`, `xhigh`, or
  `max` according to ambiguity and search depth;
- batch lanes together when worker capacity is limited.

Disclose missing isolation capabilities when they affect the user's requirements;
otherwise mention a sequential fallback only when it materially limited coverage.
