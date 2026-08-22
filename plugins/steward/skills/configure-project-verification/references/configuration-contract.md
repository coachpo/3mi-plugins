# Project verification configuration contract

Read this reference only for a deep configuration review or an authorized
`configure` operation. Ordinary discovery uses the public CLI `--help` and the
short mode contract in `SKILL.md`.

## Public command ownership

`project_verification.py` exposes `validate-profile`, `plan-impact`,
`validate-impact`, `build-ci-plan`, `validate-ci-plan`, `render-adapter`,
`render-local`, `render-github`, `review`, and `configure`.

- Static review uses `validate-profile`, `build-ci-plan` without `--output`,
  `validate-ci-plan`, renderer `--check`/`--expected`, and `review`.
- `--expected` emits deterministic SHA-256, size, and base64 candidate bytes to
  stdout without writing the project.
- Static projection writes occur only through `configure --allow-write`.
  `build-ci-plan --output`, direct renderer writes, and public renderer write
  APIs fail closed.
- `plan-impact`, `validate-impact`, and `render-adapter` belong to generated
  runtime entry points. This skill does not use them as configuration-completion
  evidence or as a static-write bypass.
- Campaign execution, evidence export/aggregation, and audit belong exclusively
  to `run-closed-loop-verification`.

## Freeze the configuration transaction

Before generating candidates, freeze the project-relative write set: the
profile, base adapter, local entry, CI plan, and provider workflow actually
authorized by the request. New projects must name the profile and adapter paths
directly rather than deriving them from nonexistent outputs.

The profile and adapter remain the authoritative inputs. `configure` validates
them and writes only the profile-declared CI plan, local entry, and workflow. It
does not create or rewrite the profile or adapter.

The writer rejects aliases, traversal, link/reparse components, input/target
overlap, target/target overlap, and case/Unicode-equivalent portable collisions.
It stages candidates under a project-root coordination lock and revalidates
inputs, targets, and parent identities before the first replacement. Observable
drift fails closed. The lock coordinates only writers using the same protocol;
do not claim atomicity against unrelated processes. Current multi-file configure
writes are enabled only where the required POSIX directory-relative and no-follow
semantics exist; other hosts remain review-only.

These details are implementation invariants enforced by the CLI. Callers report
the rejection and smallest next action rather than reproducing the transaction.

## Catalog and projection rules

Derive commands, cwd, dependencies, platforms, fixtures, and evidence only from
repository facts or explicit user choices. Treat profile and adapter commands as
untrusted executable input and inspect complete argv and side effects without
running them during configuration.

The base adapter is the sole case catalog. Include cases required by the current
authorized outcome, hard constraints, reachable risks, stable `C*`, triggered
`INV-*`, and supported `RF-*`. A source-current iteration strategy may narrow
discretionary work inside that authority; it does not remove existing contracts
or create exclusion proof. `quick` marks low-cost diagnostic cases. `full` means
the entire current catalog, not every hypothetical future scenario.

The local quick entry requires a trusted impact plan and falls back to full when
change identity, dependency closure, rename/generated relationships, or selector
self-tests are uncertain. CI full ignores the selector, preserves selector
self-tests, and partitions every catalog case exactly once across required
platforms/shards.

A CI full shard is locally `coverageMode: "narrow"` because it holds one exact
partition, while retaining the base verification-catalog fingerprint. Its local
audit proves only that shard. Aggregation proves the declared entry/case/platform
union; it does not replay global Goal/invariant/finding/fix/guardrail traceability
and cannot replace a global trace-enabled audit.

Generated entries recover only from kernel `status` and `resumeMode`. They do not
infer phase from chat memory or repeat an initialized phase on re-entry. A
blocked campaign follows the closed-loop recovery/new-root contract.

## Static completion

Configuration is complete only when every frozen file exists with intended
content, profile/adapter/CI-plan validators pass, renderer checks match exact
bytes, repository configuration tests pass, and the diff contains no path outside
the write set. This proves consumable configuration, not campaign success or
remote-platform execution.
