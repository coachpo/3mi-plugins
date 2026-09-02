# Campaign state and evidence v1

All verification state lives below
`.steward/goals/<alias>/verification/`. The execution plan is immutable after
initialization. `campaign/events.jsonl` is the sole durable state authority;
each canonical event has a contiguous sequence, previous hash, content hash,
payload, and replayable state. A per-GOAL lock protects journal mutations.

Initial execution is fail-stop. A complete unrepaired initial pass is the final
regression. A failed case opens the only repair window. `record-repair` proves
the root-cause location against the failed snapshot, records the exact source
delta, accepts the new baseline, and schedules only the failed case. A passing
targeted retest requires a fresh full regression from case one. Repeated
machine-bound failures without a new source/evidence fingerprint stop.

Source identity defaults to HEAD, index, tracked files, and non-ignored
untracked files; `.steward` and ignored build products are excluded. Explicit
file-set plans bind only the declared files plus HEAD/index. Cases must not
change protected source. Drift outside the repair window blocks and requires
manual restoration; the verifier never discards user changes.

Cases run without a shell, with bounded time/output, reduced environment,
process-group cleanup, secret redaction, and a private evidence directory.
Artifacts, results, and their manifest are write-once and digest-bound.

Audit revalidates the GOAL bundle, both plans, journal, source, final ordered
case pass, required `C*` coverage, and artifacts. Completion is current only
while those bindings remain valid. Restoring exact bytes/source restores current
completion without creating a new campaign epoch.
