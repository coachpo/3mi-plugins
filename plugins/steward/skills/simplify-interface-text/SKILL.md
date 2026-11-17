---
name: simplify-interface-text
disable-model-invocation: true
description: Audits or cleans up redundant or wordy copy on existing rendered screens by role and state. Use when the user asks to trim or tighten interface text that repeats, narrates controls, explains internals, or says a needed thing at length. Explicit invocation only. Not for new feature copy, translation, visual redesign, or behavior-preserving repository cleanup.
---

# Simplify Interface Text

Remove interface text that does not change what the reader does or knows; keep
protective text and unique information. Shorten text that is needed but wordy,
keeping everything it tells the reader. Finding nothing worth changing is valid.

Every invocation starts with a review: a scan that returns findings without
editing source, copy, configuration, or existing records; see the test-record
exception below. Present the findings list, ask once whether to clean up, and
on confirmation carry the in-scope changes through validation. Ask about the
list as a whole, not finding by finding; the user may exclude findings.

Two kinds of request change this. A request for a review only ends after the
findings list without asking. A request that says to change the text directly
without asking, or that supplies or refers to a list the user already accepted,
skips the question. Unlike
[simplify-repository](../simplify-repository/SKILL.md), this work changes
visible output on purpose. It still does not change commands, amounts, stored
facts, or server contracts.

## Establish rules, scope, and authority

Use the project's adopted interface copy rules when its contribution guide or
another authoritative document states them. Otherwise apply the interface copy
principles in
[default-policies.md](../../references/default-policies.md) and
say that you did. Do not record project policy as a side effect of an audit.

Identify the interfaces, roles, locales, and environments in scope and what is
authorized in each. To reproduce a screen state, create labeled test records
and advance them through the workflow. In a non-production environment the
request itself covers this; in production it needs the user's instruction for
that environment, and a review-only request never does it there. Leave other records alone
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
- The proposed change: remove, shorten, move, or show conditionally, with the
  replacement text for a shortened text.
- The source location, or that it is instance data.
- Whether it was observed or read from source.

Report one finding for a fact repeated in several places, naming the place
that keeps it. Record text that looks redundant but must stay, with the reason,
so a later pass does not remove it. Do not pad the list: a finding has to pass
the rule's own test of whether removal would mislead the reader or lose a fact.

## Clean up

When working from a list the user accepted, report newly found issues rather
than adding them to it.

- A shortened text keeps every fact, condition, number, unit, named term, and
  required action of the original, in the project's established terminology.
  If a text cannot be shortened without losing one of these, leave it and
  report why.
- Change every supported locale together. Write each locale's shortened text
  from the meaning rather than translating another locale's result. When a key
  is no longer referenced, delete it from every locale and its type, following
  the project's compatibility policy.
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
how the result differs from the proposal, or left unchanged and why. Give the
text before and after for each changed text. Call out every deviation from a
list the user accepted.

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
  for independent copy-source searches when useful.
