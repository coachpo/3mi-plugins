# Default Policies

The single source for the default policies Steward writes into a repository.
`write-project-docs` states them in full, with the rationale contributors need,
in the contribution guide or existing authoritative policy document.
`write-agent-guides` states them in root `AGENTS.md` as short operational rules
and links to that authoritative document. Explicit requirements from the user
or currently effective project policy take precedence over these defaults.

## Design and development principles

- Treat uncertain platform capability, resource tier, and quota as design
  space: choose the looser tier and record the assumption instead of
  pre-tightening defaults for an assumed worst case.
- Assume the overwhelming majority of requests are legitimate: do not require
  preemptive abuse handling, conservative rate limits, or adversarial hardening
  beyond the accepted requirements.
- Choose the best-case branch by default; worst-case handling is a named
  project decision, not inherited caution.
- Keep source files cohesive and navigable. When a file's size or continued
  growth makes its responsibilities hard to distinguish, important behavior
  difficult to find, or focused changes difficult to review, split it along
  cohesive responsibilities within the task's scope. Follow established
  project size limits; without them, use cohesion, navigability, and
  reviewability rather than a universal line-count cap. Do not create needless
  fragments or abstractions merely to shorten a file.

Record uncertain capability choices as working assumptions, not as observed
platform behavior. State the chosen branch with the observation that would
trigger a revisit. Do not present an assumed limit or permission as verified,
and do not drop a limit or obligation the project has actually accepted.

## Compatibility policy

- This project does not preserve backward compatibility by default. Do not retain
  compatibility layers, aliases, dual paths, or transitional code for old APIs,
  formats, configuration, or implementations unless explicitly required.
- When authorized to replace an implementation, update affected callers,
  configuration, derived contracts, tests, and documentation, and remove obsolete
  paths within the task's scope. Do not add old-field fallbacks, dual reads or
  writes, or format conversions merely because old callers might exist.
- Keep cleanup within the current task; this policy does not expand its scope.

This documentation default does not itself authorize deleting existing
compatibility code or changing public APIs.

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
