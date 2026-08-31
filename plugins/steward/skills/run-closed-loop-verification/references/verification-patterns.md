# GOAL acceptance design patterns

Translate the current GOAL into observable project-native checks before writing
the adapter. Build one small matrix with each `C*`, its required case or cases,
the command, precondition, expected result, and durable evidence file. Reject a
design that leaves a criterion optional-only or inferred from an unrelated pass.

Prefer existing build, test, lint, typecheck, integration, and workflow commands.
Use local fixtures, loopback services, fakes, deterministic data, and bounded
timeouts. A case should identify one useful failure boundary; split a long
journey when its first failed transition would otherwise be unclear.

Choose counterexamples that can disprove the completion criterion, such as
malformed or missing input, denied access, stale persisted state, replay after an
interruption, incompatible data, or scope leakage. Include them only when the
GOAL or reachable repository behavior makes them material.

Order inexpensive prerequisite checks before their consumers. Dependencies
express real execution prerequisites, not a preference for serial output. Keep
every command and fixture inside the authorized local boundary, and do not
substitute a placeholder command merely to make adapter validation pass.

Evidence should prove behavior rather than repeat command text. Put command-owned
files below `CLOSED_LOOP_EVIDENCE_DIR`, declare every required file, and mark a
file non-empty when empty output cannot prove the claim. Avoid credentials,
shared mutable services, production data, paid calls, and destructive setup.
