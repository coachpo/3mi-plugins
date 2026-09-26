---
name: parallel-repository-research
description: Investigate a repository through at least two useful independent search lanes to locate code, map architecture, inventory implementations, or trace dependencies. Read-only research; excludes code changes, test execution, and behavioral-risk adjudication.
---

# Parallel Repository Research

Use parallel workers when at least two independent repository searches help
answer the question. Handle single-point or dependent lookups directly. The
main agent owns the answer and verifies decisive evidence from worker results.

This is repository research only: inspect source, configuration, tests as text,
and read-only Git history. Do not modify files or Git state, run project code,
tests, builds or installers, or call network services. Report repository facts;
do not turn them into behavioral-risk findings, severity ratings, or test cases.

## Delegate useful questions

Resolve the target worktree. Give each worker a bounded question, the relevant
paths and exclusions, applicable instructions, and the read-only boundaries
above. In Codex, use `gpt-6-luna` for bounded read-only workers when the
delegation tool supports a model override. In Claude Code, use the plugin's
`steward-researcher` agent, which runs on a lower-cost model with read-only file
tools; handle Git history lookups directly. Otherwise use the host default;
avoid redundant searches unless independent corroboration helps resolve an
uncertainty.

Ask workers to return their conclusion, precise file locations or symbols and
the facts they support, and material conflicts or unsearched scope. Locators
should let the main agent reopen the evidence without exposing secret values.

Adapt searches as evidence or user corrections change what needs investigation.
Recheck results affected by a changed target, scope, or revision. If delegation
is unavailable, perform the useful searches directly within the same scope and
permissions. Report the fallback when it materially limits coverage or affects
a user requirement.

## Verify and answer

Reopen decisive evidence in the target repository and confirm what it supports;
worker summaries and search snippets alone do not establish a fact. Reconcile
overlaps and contradictions, and exclude claims whose evidence no longer
applies.

Answer the original question with verified file citations. State material gaps,
conflicts, or unsearched scope and their effect on the answer. Do not imply a
complete inventory when relevant areas remain unsearched. Include per-worker
details only when they explain a disagreement or the user needs an audit trail.
