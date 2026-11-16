---
name: simplify-interface-text
disable-model-invocation: true
description: Audit or clean up redundant copy on existing rendered screens by role and state. Explicit invocation only. Not for new feature copy, translation, visual redesign, or behavior-preserving repository cleanup.
---

# Simplify Interface Text

Remove interface text that does not change what the reader does or knows; keep
protective text and unique information. Finding nothing worth removing is valid.

Reviews return findings without editing source, copy, configuration, or
existing records; see the test-record exception below. A request that does not
say whether to review or clean up is a review.

Implementation requests work from a findings list the user has accepted and
carry the in-scope changes through validation. Text the request names for
change counts as accepted.
Otherwise, when no accepted list exists, produce the findings list as a review
does and stop for acceptance before editing. Unlike
[simplify-repository](../simplify-repository/SKILL.md), this work changes
visible output on purpose. It still does not change commands, amounts, stored
facts, or server contracts.

## Establish rules, scope, and authority

Use the project's adopted interface copy rules when its contribution guide or
another authoritative document states them. Otherwise apply the interface copy
principles in
[default-policies.md](../write-project-docs/references/default-policies.md) and
say that you did. Do not record project policy as a side effect of an audit.

Identify the interfaces, roles, locales, and environments in scope and what is
authorized in each. To reproduce a screen state, create labeled test records
and advance them through the workflow. In a non-production environment the
request itself covers this; in production it needs the user's instruction for
that environment, and a review never does it there. Leave other records alone
and do not remove test records unless asked. Authorization does not carry over
to another environment.

If sign-in, verification, or another blocker makes an environment unreachable,
report it and use another reachable environment only if authorized. Do not guess
addresses, credentials, or screen contents.

## Judge rendered screens

Repetition and noise exist on a screen, not in a string table. Two keys with
similar wording are not a finding unless a person sees both together, and one
key can be a finding by appearing next to a heading, badge, or control that
already says the same thing.

Walk each interface by role and state. Cover the states that change what is
shown: empty and populated, normal and exceptional, in progress and finished,
one available option and several, a capability enabled and not enabled. Read
the page as text where possible, and view it when placement matters.

Read source for states you cannot reach, and mark those findings as read from
source rather than observed. Source reading supplements the walk; it does not
replace it.

For every text, determine whether it is source or instance data such as saved
settings, managed content, or seeded records. A repository change cannot fix
instance data. List those findings separately for whoever owns the content.

## Record findings

Give each finding a stable identifier so the cleanup can be reported against
it, and record:

- The screen and the condition under which the text appears.
- The exact text.
- Which rule it breaks, and why the reader does not need it there.
- The proposed change: remove, shorten, move, or show conditionally.
- The source location, or that it is instance data.
- Whether it was observed or read from source.

Report one finding for a fact repeated in several places, naming the place
that keeps it. Record text that looks redundant but must stay, with the reason,
so a later pass does not remove it. Do not pad the list: a finding has to pass
the rule's own test of whether removal would mislead the reader or lose a fact.

## Clean up against the accepted list

Report newly found issues rather than adding them to the accepted list.

- Change every supported locale together. When a key is no longer referenced,
  delete it from every locale and its type, following the project's
  compatibility policy.
- A copy change includes the condition that renders it. Implement "do not show
  this in the normal state" from facts the screen already has, as narrowly as
  the finding requires. If a finding needs new business logic or a contract
  change, leave it and report why.
- Keep explicit confirmations, values shown nowhere else, and text that carries
  function. Before removing text that contains a value, such as a revision,
  identifier, or amount, check what relies on it: the reader, a support
  workflow, or a test that uses it as evidence of state.
- Update tests and documentation that assert or describe the changed text. Do
  not add tests that only prove a sentence was removed.
- Leave instance data unchanged unless editing it in that environment is
  authorized.

## Validate

Run the project's checks for the affected code, including interface tests that
assert the changed screens. When an interface test fails, compare it with the
pre-change baseline before attributing the failure to the cleanup. Report
pre-existing stale assertions rather than rewriting them to pass.

View the changed screens in the affected states where that is possible. State
which screens were viewed, which were only covered by tests, and which test
suites were updated but not run. Later edits invalidate affected results.

## Report the result

For each finding identifier, state whether it was changed, changed in part and
how the result differs from the proposal, or left unchanged and why. Call out
every deviation from the accepted list.

State the validation actually run and its results, the scope left unverified,
the instance-data findings that remain for their owner, and any test records
or local state left behind.

## Compose with other Steward skills

- Use [write-project-docs](../write-project-docs/SKILL.md) when the user wants
  the interface copy rules recorded in project documentation.
- For behavior-preserving cleanup, suggest
  [simplify-repository](../simplify-repository/SKILL.md), which requires
  explicit invocation.
- Use [parallel-repository-research](../parallel-repository-research/SKILL.md)
  for independent copy-source searches when useful and authorized.
