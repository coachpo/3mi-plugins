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
needs, side effects, and evidence before initialization. If a trustworthy runner
does not exist after implementation, report the blocker rather than weakening
the acceptance plan or inventing a placeholder.
