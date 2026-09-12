# Campaign recovery and evidence

Verification lives below `.steward/goals/<alias>/verification/`. The execution
plan is immutable; `campaign/state.json` is the durable state authority. The
engine atomically records phases under a per-GOAL lock and resumes interrupted
attempts. Each assigned case gets a result even when another case fails.

## Diagnose and repair

Use `lastFailure` and its artifacts to distinguish a source defect from an
environment or execution-binding problem. `REPAIR_REQUIRED` alone does not prove
that source needs changing. For a confirmed, authorized source fix, submit:

```json
{
  "rootCause": "why the case failed",
  "rootCauseSource": {"path": "src/x.py", "lineStart": 10, "lineEnd": 24},
  "fixSummary": "the change made"
}
```

These three fields are exact; `rootCauseSource` additionally allows `symbol`.
`record-repair` checks the location against the failed source snapshot and
records the actual delta, then schedules that case for targeted retesting.
Once failures are resolved, any campaign with repairs runs all cases against
the final baseline before completion. New failures reopen the repair loop.
Repeated failures without new source or evidence stop rather than looping.

## Choose the recovery route

- Temporary environment `BLOCKED`: restore the prerequisite within existing
  authority and `advance`. Completed cases remain recorded.
- Completion-check `BLOCKED`: resolve the reported evidence or integrity issue
  before advancing. Restore original evidence only when its exact bytes are
  available; never manufacture a passing artifact.
- Same-plan `init`: loads the existing campaign idempotently. A different plan
  is rejected as `CAMPAIGN_CONFLICT`.
- Environment or binding failure recorded as `REPAIR_REQUIRED`, changed argv,
  cwd or timeout, or re-proving a completed campaign: use a fresh campaign.
- Wrong acceptance intent, waiver, or source policy: redraft within the user's
  authority, preserving the existing immutable GOAL bundle.

Before replacing a campaign, preserve and verify its entire `verification/`
directory in an ignored archive in the same worktree. Prepare the corrected
binding, then use existing explicit removal authority or request it before
removing the active directory. Initialize the fresh campaign with the unchanged
GOAL and acceptance plan. A status query or repeated `advance` does not reset a
completed campaign.

## Interpret source and completion evidence

Source identity normally includes HEAD, index, tracked files, and non-ignored
untracked files; `.steward/` and ignored build outputs are excluded. Explicit
file-set plans bind only the declared files plus HEAD/index. Between-call edits
become a new baseline with a drift warning; they do not overwrite user changes.
A case changing protected source during execution fails. Repairing an ignored
runner cannot count as a protected-source fix: it must be tracked or declared
in the original file set.

Artifacts and manifests are write-once and digest-bound. Draft-declared writable
byproducts are captured and restored byte-exactly; waived non-required failures
remain recorded as unmet optional intent. The completion check revalidates the
bundle, both plans, relied-upon artifacts, and required criterion coverage. With
repairs, its latest case evidence comes from the final regression.

`COMPLETE` records historical acceptance. Compare the current report's
`sourceFingerprint` with `completion.sourceFingerprint` before claiming the
current worktree passes. For a mismatch, inspect actual changes and dependencies;
if behavior is affected or uncertain, current acceptance remains incomplete and
needs a fresh campaign. Artifact or binding tampering can likewise yield current
`INCOMPLETE` despite the persisted historical status.
