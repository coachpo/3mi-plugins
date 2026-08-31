# Campaign state and evidence

The campaign root is fixed at `.steward/verification/campaign`. The kernel owns
everything below it. Never hand-edit, delete, relocate, or selectively copy its
journal, projections, locks, attempts, or artifacts.

## Durable state

`events.jsonl` is the schema-5 append-only authority. Each event has a
contiguous sequence, previous-event digest, and canonical content digest.
`state.json` and `summary.json` are deterministic projections. Status reports
surface a projection mismatch; a mutating command rebuilds projections from a
valid journal while holding `campaign.lock`. Audit still rejects any mismatch
that was not repaired through that normal recovery boundary.

Initialization is create-only and persists:

- kernel `0.5.0`, adapter digest, ordered case catalog, and runtime platform;
- canonical target-worktree identity (`targetWorktreeRoot`, `gitDir`, and
  `gitCommonDir`);
- the GOAL path, version, digest, and criterion IDs;
- a complete source snapshot;
- `repairPolicy`, either `within-goal` or `verify-only`, and `repairCount: 0`.

The policy defaults to `within-goal`. It has no numeric repair limit. A campaign
initialized as `verify-only` cannot be widened while resuming it.
Every load re-resolves the worktree identity and runtime platform. A mismatch
blocks mutation and prevents current completion; copying `.steward` to another
repository or sibling worktree cannot transfer `COMPLETE` acceptance.

## Execution lifecycle

Initial acceptance runs in adapter order and stops at the first `FAILED` or
`BLOCKED` case. Required unavailable platforms block. Optional unavailable
platforms are recorded as `NOT_RUN`. A successful initial pass becomes
`READY_FOR_REGRESSION`.

For a project-source defect under `within-goal`:

1. Prove the latest failure's root cause and make the smallest GOAL-scoped edit.
   Use the FAILED command or `status` output's read-only `latestFailure` and
   `fixContext` projections. After identifying the root-cause project path, run
   `status --source-path <path>` and copy `rootCauseSource.failedSha256` from the
   matching `selectedSourceFiles` entry. The default projection returns no file
   entries, and one query accepts at most 64 unique normalized paths. Do not
   inspect `state.json` or pre-capture a digest.
2. Fill [`../assets/fix-audit.template.json`](../assets/fix-audit.template.json).
3. `record-fix` checks the exact failure binding, current fixed fingerprint,
   source location and failed-file digest from the failure snapshot, affected
   `C*`, and complete added/modified/deleted/mode-only delta before incrementing
   `repairCount`. A deleted root-cause file is valid only when that exact path is
   marked `deleted` in the delta.
4. `retest` runs only the failed case. A passing retest resumes remaining
   initial cases or returns to a fresh regression, according to the failed
   round.

Another repair is permitted only when the newest failure supplies distinct
machine-bound evidence or observable progress. Free-form explanation changes do
not count. Stop before editing when the same failure signature, failed-file
digest, and normalized source path/range/symbol recur; the next edit
rests on the same disproved premise; the root cause is not established; the
repair would leave GOAL scope; project source changed outside the declared
repair; or the failure is an environment/capability blocker.

Final regression always starts at case one and binds every run to one source
fingerprint. Any source change during it records a permanent campaign
invalidation. A successful regression yields `AUDIT_REQUIRED`, not completion.
The first successful audit appends one `audit_succeeded` event bound to that
final regression, the observed final source, and the adapter catalog. Replay of
that event durably sets `status: COMPLETE`, clears `resumeMode`, and preserves
the binding; repeated audits append nothing.

## Runner and artifacts

The runner uses `shell=false`, a bounded timeout, a reduced environment, and a
per-run evidence directory. It drains bounded stdout/stderr, redacts recognizable
secrets, terminates process trees, rejects artifact links and special files, and
binds every persisted file by size and SHA-256 in artifact manifest v1.

Exit failure, timeout, or missing declared evidence is `FAILED`. Unsafe process
cleanup, secret-like output, source drift, catalog drift, or path uncertainty is
`BLOCKED`. Preserve all terminal artifacts, including failed runs.

`resume` reconstructs authority from the hash-chained journal. If an operation
ended with an open attempt, it records the interruption and starts a new attempt
for that round; it never relies on chat memory.

## Completion

Audit succeeds only when:

```text
all required and runnable optional cases PASS in one final regression
AND every GOAL C* has a required final-PASS case
AND journal, projections, source, catalog, and artifacts verify exactly
```

The resulting `completionStatus` is `COMPLETE`. Otherwise report the stable
rejection codes, failed case, evidence, repair count, and smallest safe next
action without reducing the acceptance standard. Durable `status: COMPLETE`
records that an audit succeeded, but current `completionStatus` remains
`COMPLETE` only while the GOAL, source, catalog, projections, and artifacts still
revalidate. Later drift or tampering does not rewrite the successful audit event.
