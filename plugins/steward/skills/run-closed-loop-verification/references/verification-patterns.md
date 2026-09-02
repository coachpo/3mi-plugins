# GOAL acceptance design patterns

Map every GOAL `C*` to the smallest project-native command that can directly
prove or disprove it. Reuse one case for multiple criteria when the same
observable result genuinely covers them.

Prefer existing test, build, lint, typecheck, integration, and workflow commands.
Use local deterministic data and bounded timeouts. Order inexpensive prerequisite
checks first; execution is fail-stop in Adapter order.

Use counterexamples only when the GOAL or reachable behavior makes them material.
Command exit status and bounded output are evidence by default. Declare files
below `CLOSED_LOOP_EVIDENCE_DIR` only when a criterion requires a durable
artifact that ordinary output cannot prove.

Review the executable, complete `argv`, working directory, environment needs,
and side effects. Do not use a placeholder command or treat an Adapter declaration
as permission for an external capability.
