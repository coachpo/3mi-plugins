# Execution plan v1

Draft owns immutable acceptance intent. Verification binds each acceptance case
to current project-native execution without changing its order, identity,
required flag, platform, criterion coverage, assertion, or evidence contract.

The execution plan contains only `schemaVersion: 1` and an ordered `cases`
array. Every case contains exactly:

- `id`, matching the acceptance case in the same position;
- non-empty non-shell `argv`;
- an existing safe project-relative `cwd`;
- a finite positive `timeoutSeconds`, at most seven days;
- a non-empty `bindingRationale` explaining why the command proves the frozen
  assertion.

Inspect the executable, full argv, working directory, platform, environment
needs, side effects, and evidence before initialization. Initialization
already revalidates everything `init` needs, so no separate preflight command
is required. If a trustworthy runner
does not exist after implementation, report the blocker rather than weakening
the acceptance plan or inventing a placeholder.

The binding inherits two Draft-declared relaxations mechanically; it never
invents them:

- A non-required case with `onFailure: "waive-with-report"` may fail without
  stopping the attempt: the failure is journaled with full evidence, the
  attempt ends as `WAIVED`, and audit re-checks the waiver against the final
  same-source regression. Required cases always stop.
- Files in `sourcePolicy.writable` may be created or modified by cases. They
  sit outside the protected source fingerprint, are snapshotted before each
  run, and are restored byte-exact afterwards; the capture and the recorded
  mutations live in the case artifact.

A runner that lives under an ignored build directory is not part of the
protected source, so repairing it cannot open the repair window. When the
runner is a repair target, Draft must either place it under a tracked path or
declare it explicitly; otherwise report the blocker at init time.
