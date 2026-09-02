# Campaign state and evidence

The Campaign root is fixed at `.steward/verification/campaign`. The kernel owns
its journal, lock, attempts, and artifacts.

## Durable state

`events.jsonl` is the sole durable authority. Each event has a contiguous
sequence and previous-event/content digest. Current state and summaries are
derived by replay; no separate persisted projections are maintained.

Initialization records the Adapter digest, ordered cases, GOAL and worktree
bindings, runtime platform, and source baseline. A load revalidates those
bindings. Copying Campaign files to another worktree cannot transfer completion.

## Lifecycle

Initial cases run in order and stop at the first `FAILED` or `BLOCKED` result.
When every case passes without a repair, that same-source complete pass is the
final regression. A repair records the kernel-derived failure binding and source
delta, runs only the failed case as a targeted retest, then requires one fresh
full regression.

The repair note contains only:

- `rootCause`;
- `rootCauseSource.path`, `lineStart`, `lineEnd`, and optional `symbol`;
- `fixSummary`.

The kernel derives and journals all identifiers, fingerprints, affected
criteria, failed-file digest, and changed paths. Rewording cannot bypass a
repeated failure with the same signature, source path/range, and failed digest.

A source change during final regression invalidates that attempt but not the
whole Campaign. Restore the recorded repair baseline and run `advance` to start
a fresh regression.

## Runner and artifacts

Cases use `shell=false`, a bounded timeout, reduced environment, bounded output,
secret redaction, process-tree cleanup, and a per-run evidence directory.
Execution failure, timeout, or missing declared evidence is `FAILED`; an unsafe
execution boundary is `BLOCKED`.

The final audit validates the current GOAL, worktree, platform, Adapter, source,
criterion coverage, final regression, and final artifacts. Earlier failed-run
artifacts remain diagnostic history but do not independently invalidate current
completion.

## Completion

Completion requires:

```text
all required and runnable optional cases PASS in one same-source full regression
AND every GOAL C* has a required final-PASS case
AND the current final audit succeeds
```

A successful audit appends one idempotent completion event. Later GOAL, source,
Adapter, worktree, or final-artifact drift makes current completion incomplete
without rewriting the historical event.
