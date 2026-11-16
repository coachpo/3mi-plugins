# Default Policies

The single source for the default policies Steward writes into a repository.
`write-project-docs` states them in full, with the rationale contributors need,
in the contribution guide or existing authoritative policy document.
`write-agent-guides` states them in root `AGENTS.md` as short operational rules
and links to the authoritative policy where it exists. Explicit requirements
from the user or currently effective project policy take precedence over these
defaults.

## Contents

- [Design and development principles](#design-and-development-principles)
- [Compatibility policy](#compatibility-policy)
- [Deployment status](#deployment-status)
- [Non-production data and secrets](#non-production-data-and-secrets)
- [Interface copy](#interface-copy)
- [Operating context](#operating-context)
- [Commit and pull request conventions](#commit-and-pull-request-conventions)

## Design and development principles

- Platform billing tiers and quotas are not design inputs. Whether or not the
  current tier is known, use the loosest officially supported option as the
  working assumption; do not estimate usage, verify quotas, or optimize for
  them. Tighten only for an observed limit (an actual runtime quota or resource
  error) or an accepted requirement; a tier limit listed in official
  documentation is not by itself grounds for tightening.
- Design for ordinary, legitimate use. Do not add preemptive abuse handling,
  conservative rate limits, or adversarial hardening beyond accepted
  requirements. Make worst-case handling an explicit project decision and
  state what evidence or requirement would trigger it. Preserve accepted
  security, privacy, and operational obligations and applicable mandatory
  requirements.
- Keep source files cohesive and navigable. When a file's size or continued
  growth makes its responsibilities hard to distinguish, important behavior
  difficult to find, or focused changes difficult to review, split it along
  cohesive responsibilities within the task's scope. Follow established
  project size limits; without them, use cohesion, navigability, and
  reviewability rather than a universal line-count cap. Do not create needless
  fragments or abstractions merely to shorten a file.
- Scope design, planning, and implementation around enabling core business
  flows and correct business outcomes. Do not proactively add requirements
  that are unnecessary at the current stage unless they are requested or
  required by an accepted constraint.
- Incorporate a confirmed applicable mandatory requirement as a requirement or
  design constraint even when it does not block a core flow, and meet an
  obligation the current work triggers when it is due. Recording an obligation
  does not by itself put its implementing features in scope for the current
  stage. Assess applicability from the actual business context, not from a
  label; treat unresolved applicability as unconfirmed, not as
  non-applicability.

When a document records a tier or quota choice made under the first principle,
record it as a working assumption, not as observed platform behavior, with the
observation that would trigger a revisit. Do not present an assumed limit or
permission as verified, and do not drop a limit or obligation the project has
actually accepted.

## Compatibility policy

- This project does not preserve backward compatibility by default. Do not retain
  compatibility layers, aliases, dual paths, or transitional code for old APIs,
  formats, configuration, or implementations unless explicitly required.
- When authorized to replace an implementation, update affected callers,
  configuration, derived contracts, tests, and documentation, and remove obsolete
  paths within the task's scope. Do not add old-field fallbacks, dual reads or
  writes, or format conversions merely because old callers might exist.
- Keep cleanup within the current task; this policy does not expand its scope.
- Migration code follows the project's deployment status. When the project
  shows no sign of a production deployment, migration code need not preserve
  existing data or history: rewrite, squash, or regenerate migrations when that
  is simpler. With a production deployment, migration code that runs in
  production must stay correct there and released migrations are not rewritten
  or squashed; only the non-production environment's own data handling is
  relaxed.

State the migration branch that applies together with the deployment status it
rests on, decided as described under Deployment status. This documentation
default does not itself authorize deleting existing compatibility code,
changing public APIs, or rewriting existing migrations.

## Deployment status

Both skills decide whether the project has a production deployment the same
way, wherever they state it:

- Write that it has one from the user's statement, an accepted project
  document, or a sign in the repository such as deployment configuration, a CI
  deploy job, a production environment file, or a release record.
- When the repository shows no such sign and the user has not said otherwise,
  write that it has none. Record this as a working assumption resting on the
  absence of those signs, and name them as what would trigger a revisit.

## Non-production data and secrets

- Treat an environment and its data as non-production unless it is
  identifiable as production: it is one of the project's listed production
  identifiers; its name, host, branch, project, or configuration is marked
  `prod`, `production`, or `live`; it comes from production configuration or
  environment files; it shows real customer data or real payments; or the user
  says it is production.
- Non-production data is disposable. When a task changes schema or data there,
  cut over directly: drop, truncate, reset, recreate, or reseed as the simplest
  path requires, without backups, dry runs, staged or reversible migrations,
  backfills, or confirmation steps. Confine such operations to the environment
  the task targets.
- Treat a secret as a test value unless it is identifiable as production or
  real-account: a live-marked name or prefix, a value from production
  configuration or environment files, or one the project lists as such. Pass
  test values directly as command arguments, environment variables, or tool
  arguments. Do not commit any secret or print it in logs or reports.
- In production, every destructive or migration action and every use of a
  production or real-account secret needs the user's explicit instruction.

This policy removes confirmation for non-production data operations only. It
does not authorize commits, pushes, deployments, or other external writes.

## Interface copy

Conditional: state these only for a repository whose source renders text to
people through a user interface. Omit the section for libraries, services, and
tools without one.

Keep a sentence only if removing it would make the reader act wrongly or lose a
fact they cannot get elsewhere on the same screen.

- State each fact once per screen, at the place closest to the action it
  informs.
- Show a notice only when it changes what the reader does. The normal state
  gets no banner; empty sections and sections for a capability that is not
  enabled are not rendered.
- Keep internal mechanics off the screen: data-model terms, validation order,
  configuration names, internal identifiers, and algorithm descriptions.
- Do not narrate a control whose label is sufficient.

These rules remove explanation, not protection. Keep explicit confirmations on
irreversible or financial actions, a value the screen shows nowhere else, and
text that carries function.

Supported locales, units, terminology, and named exceptions are project facts:
write them from the repository and accepted decisions, not from this default.

## Operating context

Conditional: state these only for a repository that is an operated product, as
shown by its product documentation or stated by the user. Omit the section for
libraries, tools, and internal utilities.

- Do not assume an operating entity, operating location, or launch market that
  the user has not specified or the project has not established; design
  market-neutrally wherever those details are unresolved.
- A known operating location is business context, not a request to localize
  for that market or to analyze its compliance.
- Analyze a specific market or operating arrangement only when the user
  requests it, or as a limited check needed to honor an accepted constraint or
  to determine or meet a mandatory obligation relevant to the current work.

The operating entity, operating location, launch market, and the obligations
confirmed or still unconfirmed are project facts: record them in product
documentation from the user's statements and accepted decisions, not from this
default.

## Commit and pull request conventions

Conditional: an established repository convention takes precedence. Check the
commit history, the contribution guide, commit-lint configuration, and pull
request templates first, and state these defaults only where no convention
exists. State the pull request part only for a repository that uses pull
requests.

Commit messages:

- Use Conventional Commits, `<type>: <description>`, with the type one of
  `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `build`, `ci`, or `perf`.
- Write the description in English, lowercase and imperative, with no trailing
  period. Keep the subject concise, preferably within 72 characters.
- Add a scope such as `feat(auth):` only when it materially improves clarity.
- Use a single subject line unless a body is necessary.
- Describe only what the diff contains.

Pull requests:

- Title: the same format as a commit subject. For several commits, use the type
  that best describes the overall change to a reviewer.
- Description: in English, with these sections, omitting any that would be
  empty. Summary: one to three sentences on what changes and why. Changes:
  notable changes grouped by area, naming schema, migration, configuration,
  environment variable, and public API changes, with breaking changes led by
  `**Breaking:**`. Testing: the commands actually run and their results, or
  "Not tested". Notes: reviewer-relevant caveats only.
- Base the description only on the branch's diff and commits. Reference an
  issue only when it appears in the branch name, the commits, or the request.
  Leave out timelines, effort estimates, and assignee suggestions.

These conventions do not authorize committing, pushing, or opening a pull
request.
