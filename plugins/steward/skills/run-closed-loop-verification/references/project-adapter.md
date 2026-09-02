# Project adapter v2

The Adapter is the reviewed local verification plan. Its only supported location
is `<worktree>/.steward/project-adapter.json`; project and Campaign roots are
derived from that fixed location rather than repeated in the document.

Start from [project-adapter.template.json](../assets/project-adapter.template.json).
Unknown fields fail.

## Contract

The top level contains only:

- `schemaVersion: 2`;
- `source`, using `git`, `manifest`, or `files`, with `.steward` excluded;
- `goalContract`, binding `.steward/goal.txt`, contract version 1, and its
  canonical digest;
- one ordered, non-empty `cases` array.

Each case contains only:

- `id`, `required`, and `platform`;
- unique `coversCriteria` IDs;
- non-shell `argv`, project-relative `cwd`, and a bounded
  `timeoutSeconds`;
- optional required and non-empty files below `CLOSED_LOOP_EVIDENCE_DIR`.

Cases are deterministic and fail-stop in document order, so a separate dependency
graph is unnecessary. Every GOAL `C*` needs at least one required case. An
unavailable required platform blocks; an unavailable optional case is
`NOT_RUN`.

The Adapter describes local execution but grants no permission. Inspect commands,
environment needs, services, devices, credentials, and side effects before
initialization. If a criterion lacks a trustworthy runner, report that blocker
instead of creating a placeholder.
