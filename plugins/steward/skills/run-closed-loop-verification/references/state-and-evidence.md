# Campaign state and evidence v1

All verification state lives below
`.steward/goals/<alias>/verification/`. The execution plan is immutable after
initialization. `campaign/state.json` is the durable state authority,
rewritten atomically (write-temp-then-replace) after every phase. A per-GOAL
lock protects state mutations. One `advance` chains the mechanical phases and
stops only at human decision points: `REPAIR_REQUIRED`, `BLOCKED` (including a
rejected completion check), or `COMPLETE`; each phase still saves the current
state, and interruption resumes the in-progress attempt exactly where it
stopped.

An attempt runs every case_id assigned to it to a terminal result; one case
failing does not stop the others, so every case in that attempt gets recorded
evidence. Any case left failing without a declared waiver opens a repair
window for that case specifically. `record-repair` proves the root-cause
location against the failed snapshot, records the exact source delta, accepts
the new baseline, and schedules only that one case for a targeted retest —
every other case keeps standing on its existing evidence rather than being
rerun. Repeated machine-bound failures without a new source/evidence
fingerprint stop.

Source identity defaults to HEAD, index, tracked files, and non-ignored
untracked files; `.steward` and ignored build products are excluded. Explicit
file-set plans bind only the declared files plus HEAD/index. Source edits
observed between calls are absorbed as the new baseline and recorded as a
drift warning rather than blocking the campaign; the verifier never discards
or overwrites a user's edits to do this. A case that modifies protected
source during its own run is instead treated as a failure requiring a fix —
typically correcting the runner or declaring the path in
`sourcePolicy.writable` — routed through the same repair window as any other
failure, not a silent baseline change.

Cases run directly, with a bounded timeout and output size, and a private
evidence directory. Artifacts, results, and their manifest are write-once and
digest-bound. Files listed in `sourcePolicy.writable` are snapshotted before
each case and restored byte-exact afterwards; the snapshot and the recorded
mutations live in the case artifact, and the protected source fingerprint
excludes them by construction. A non-required case that Draft declared
`onFailure: "waive-with-report"` may fail without opening a repair window for
it; its evidence stays attached to the attempt that produced it, independent
of whether that same attempt also has an unrelated blocking failure.

The completion check assembles each acceptance case's most recent evidence
across attempts — a targeted retest's result overrides only the case(s) it
reran — then revalidates the GOAL bundle, both plans, every relied-upon
artifact, and required `C*` coverage. It runs inline as soon as no case is
left with an unwaived failure, immediately after the initial pass or after a
retest closes the last one, rather than as a separate resumable phase.
Completion is current only while those bindings remain valid; a later tamper
or authority change shows up as `INCOMPLETE` on the next check without
changing the persisted campaign status. Restoring exact bytes/source restores
current completion without creating a new campaign epoch.
