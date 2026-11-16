---
name: parallel-repository-research
description: Investigates a repository through at least two useful independent read-only search lanes. Use when locating code, mapping architecture, inventorying implementations, or tracing dependencies needs several separate searches. Not for code changes, test execution, or behavioral-risk adjudication.
---

# Parallel Repository Research

Invoking this skill authorizes read-only delegation within the requested
scope, whether the user asked for it or it was selected automatically. Use
parallel workers when at least two independent repository searches help answer
the question. Handle single-point or dependent lookups directly.

This is repository research only: inspect source, configuration, tests as text,
and read-only Git history. Do not modify files or Git state, run project code,
tests, builds or installers, or call network services. Report repository facts;
do not turn them into behavioral-risk findings, severity ratings, or test cases.
These limits cover the research itself, not the rest of the task it serves.

## Delegate useful questions

Resolve the target worktree. Give each worker a bounded question, the relevant
paths and exclusions, applicable instructions, and the read-only boundaries
above. In Claude Code, use `steward:steward-researcher` for file searches and
check Git history yourself; otherwise use the host default. Avoid redundant
searches unless independent corroboration helps resolve an uncertainty.

Ask workers to return their conclusion, precise file locations or symbols and
the facts they support, and material conflicts or unsearched scope. Locators
should let the main agent reopen the evidence without exposing secret values.

Adapt searches as evidence or user corrections change what needs investigation.
Recheck results affected by a changed target, scope, or revision. If delegation
is unavailable or the user has restricted it, perform the useful searches directly within
the same scope and permissions. Report the fallback when it materially limits
coverage or affects a user requirement.

## Verify and answer

Reopen decisive evidence in the target repository and confirm what it supports;
worker summaries and search snippets alone do not establish a fact. Reconcile
overlaps and contradictions, and exclude claims whose evidence no longer
applies.

Answer the original question with verified file citations. State material gaps,
conflicts, or unsearched scope and their effect on the answer. Do not imply a
complete inventory when relevant areas remain unsearched. Include per-worker
details only when they explain a disagreement or the user needs an audit trail.
