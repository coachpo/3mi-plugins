# Project adapter v2

The adapter is executable project-local input. Read and inspect every command and
declared effect before creating or running it. Its only supported location is
`<worktree>/.steward/project-adapter.json`; `projectRoot` is `..` relative to
that file and `campaignRoot` is `.steward/verification/campaign`.
The project root must be the exact top level of a Git worktree. Validation also
replays the shared goal-workspace v1 view, including root ignore, tracked-state,
sole context, and canonical GOAL checks.

Start from [`../assets/project-adapter.template.json`](../assets/project-adapter.template.json).
Validation is strict: all listed fields are required and unknown fields fail.

## Top-level contract

- `schemaVersion` is `2`.
- `projectId` is a stable, non-empty local identifier.
- `source.provider` is `git`, `manifest`, or `files`.
  - `git` inventories tracked and unignored untracked files.
  - `manifest` names a JSON string array, or an object containing only `files`.
  - `files` contains the complete explicit source path array.
- `source.excludes` contains `.steward`. The verifier never fingerprints its
  own adapter, campaign, GOAL, or fix documents as project source.
- `localOnly.enabled` is `true`. A case can use only capabilities listed in
  `localOnly.allowedExternalCapabilities`; this declaration does not grant
  permission by itself.
- `goalContract` names `.steward/goal.txt`, contract version `1`, and the
  canonical digest emitted by the shared GOAL validator.
- `cases` is a non-empty ordered array. Dependencies point only to earlier
  cases, so execution remains deterministic and fail-stop.

## Case contract

Each case contains exactly:

- `id`, `required`, `platform`, and ordered `dependsOn`;
- unique `coversCriteria` IDs from the current GOAL;
- a non-shell `argv` array, project-relative `cwd`, positive bounded
  `timeoutSeconds`, optional fixture, and declared external capabilities;
- `evidence.requiredFiles` and its subset `evidence.nonEmptyFiles`, both
  relative to the per-run directory exposed as `CLOSED_LOOP_EVIDENCE_DIR`.

Every GOAL `C*` must be covered by at least one required case. A case may cover
several criteria. Infrastructure cases may cover none, but optional-only
coverage cannot satisfy a criterion. Unknown or duplicate criterion IDs fail
before campaign initialization.

`platform` is one of `any`, `linux`, `darwin`, `windows`, or `posix`. An
unavailable required case blocks acceptance. An unavailable optional case is
recorded as `NOT_RUN`; an optional case that is runnable must pass final
regression.

## Creation and validation

Design the complete adapter in memory first. Use project-native deterministic
runners and concrete observable evidence. If a criterion has no trustworthy
runner, report the blocker without writing a placeholder adapter.

Create the adapter only when it is absent and the campaign namespace is also
absent. An existing invalid adapter, an existing campaign without its adapter,
or a partial campaign is an integrity failure; do not overwrite or rebuild it.
Then run:

```text
python3 -B "<skill-dir>/scripts/campaign.py" validate-adapter --adapter "<worktree>/.steward/project-adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" observe-source --adapter "<worktree>/.steward/project-adapter.json"
```

Adapter validation rejects link traversal, paths outside the project, unsafe
source entries, secret-like argv, unsupported capabilities, invalid fixtures,
incomplete GOAL coverage, or an invalid GOAL workspace. Treat these as design defects rather than
loosening the contract.
