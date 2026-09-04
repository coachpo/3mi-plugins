# Claude Code adapter

Read this adapter only when the current host is Claude Code.

Delegate a lane to the built-in `Explore` subagent only when its actual tool
surface mechanically permits repository reads while excluding writes, network
access, and further delegation. Do not infer this guarantee from the agent name
or prompt; use the sequential fallback when it is unavailable.

For an eligible delegated lane:

- request `model: haiku`;
- select per-lane `searchDepth` from `quick`, `medium`, or `very thorough`;
- repeat the complete worker input contract in the Explore prompt;
- batch lanes together when worker capacity is limited.

`searchDepth` controls search work, not reasoning effort. When the sequential
fallback applies, note the reason in the final answer only if it materially
limited coverage.
