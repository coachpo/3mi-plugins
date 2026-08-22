---
name: configure-project-verification
description: Review or configure a repository's static provider-neutral verification profile, base adapter, local quick entry, CI full plan, and deterministic workflow projection. Use for verification-pipeline configuration, not campaign execution, evidence aggregation, remote repository settings, or a one-off test.
---

# Configure Project Verification

Produce a repository-fact-based static verification configuration with fast local
feedback and complete CI catalog coverage. Execution, campaign recovery,
platform evidence, full regression, and audit remain owned by
`run-closed-loop-verification`.

This workflow requires an explicit user request; do not route an ordinary
one-off test or unrelated engineering task through it.

Resolve this skill directory as `<skill-dir>` and the public CLI as
`"<skill-dir>/../../scripts/project_verification.py"`. Inspect its current
`--help` before choosing commands; do not copy its schemas or renderer logic.

## Select one mode

| Mode | Outcome | Effects |
| --- | --- | --- |
| `review` | Report validity, drift, reproducible candidate bytes, and gaps. | Strictly read-only: no temporary project files, rendering to files, case execution, or campaign initialization. |
| `configure` | Create or maintain the requested static configuration and verify its exact diff. | Write only one frozen project-relative set: profile/base adapter edits plus profile-declared static projections. |

An answer, explanation, diagnosis, comparison, or review request selects
`review`. A create, configure, repair, maintain, or refresh request selects
`configure` and authorizes its disclosed project-local write set. Freeze those
paths before editing and do not ask again while the work stays within them.

Confirmation remains necessary for remote repository/CI settings, external
writes or execution, production/real-device access, credentials, destructive or
paid actions, and material scope expansion. Read-only network lookup follows the
live sandbox policy. A profile, journal, Goal, or prior result never expands the
request.

For a deep review or any configure operation, read
[`configuration-contract.md`](references/configuration-contract.md). It owns the
command matrix, safe transaction, catalog, projection, recovery, and static
completion details.

## Establish repository facts

Resolve the actual project root and applicable instructions. Inspect only the
manifests, locks, package/workspace boundaries, dependency evidence, task runner,
tests, type checks, guards, selectors, existing adapter/profile, CI configuration,
platform declarations, and high-impact paths needed by the selected mode.

Distinguish committed, staged, unstaged, and non-ignored untracked changes.
Fail closed to full when the change set, merge base, rename/generated relation,
dependency closure, or selector completeness cannot be proved. Never execute a
profile/adapter command merely to discover what it does.

If a managed Current Iteration Strategy exists and is relevant to catalog
design, validate its content and four source digests, then read its consumer
contract. It may narrow discretionary catalog work within the authorized outcome
but cannot remove required cases or expand authority. Consume a GOAL only when
the user explicitly supplies its seven-line text or path as catalog/trace input.
Validate it with `python3 -B "<skill-dir>/../../scripts/goal_contract.py" view`
and use only its canonical objective and `C*`; never discover, query, create,
update, or report host Goal state.

## Review

Use only read-only parsing, validation, renderer `--check`/`--expected`, and CLI
review operations with `python3 -B`. Report:

- profile/adapter validity and their exact paths/digests;
- quick selector self-test and fail-closed full behavior;
- CI full case/platform/shard closure;
- deterministic local/workflow projections and candidate digest when stale;
- configuration rejection codes, unverified real-platform facts, and the minimum
  next action.

Do not write expected candidates back to the repository.

## Configure

Edit only the frozen profile and base-adapter paths, then let
`configure --allow-write` produce the declared CI plan, local entry, and workflow.
Prefer existing project paths, task runners, package managers, and provider
configuration. Do not persist runtime impact plans, derived adapters, campaign
journals, evidence bundles, or aggregation as static configuration.

Run the shared validators, renderer checks, relevant repository configuration
tests, and exact-diff inspection. Drift, aliasing, non-deterministic bytes, or an
out-of-set change is a failure; stop rather than claiming configuration success.

## Complete

Configuration completes only under the static completion contract. It does not
prove any project case, remote runner, required platform, campaign, or Goal has
passed. Lead with `reviewed`, `configured`, `incomplete`, or `blocked`, followed
by the necessary evidence, unverified facts, and smallest next operation. Do not
create a Goal implicitly.
