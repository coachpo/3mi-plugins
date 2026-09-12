# Change-request research contract

Use this reference to establish the analysis contract, validate lane results, and
write the final answer. The structures are answer-local and conversational; they
do not authorize a file write or create project authority.

## Establish the ResearchContract

Keep the following information in the conversational contract. Field names are
organizing aids, not a parser contract:

- `requestRaw`: the request and subsequent user corrections, plus a plain-language
  restatement of what the user is asking for and has already accepted (outcome,
  included/excluded scope, constraints, priorities, and prior approvals). No ID scheme is needed —
  keep it in your own words and point back to it directly when you rely on it;
- target, exact `targetRoot` when repository evidence applies, actors,
  environment, constraints, assumptions, `include`, and `exclude`;
- `sourceBinding`: revision, installed versions, deployment mode, jurisdiction,
  and research `asOf` date that materially affect applicability;
- required `applicableInstructions`: the lane-relevant user constraints and
  applicable `AGENTS.md` sources and rules, or `none-found`; never copy hidden
  host, system, or developer text;
- material `researchQuestions` with stable question IDs;
- lanes and their dispatched input snapshots, each mapped to the relevant
  questions and one capability class;
- explicit user or host limits, their sources, and the stopping condition;
  record query, source, time, and concurrency estimates when useful for
  coordination, keeping these estimates distinct from hard limits.

Do not turn an assumption, repository behavior, or external recommendation into
part of what the user asked for or already accepted.

Only already-dispatched lane inputs remain frozen as evidence snapshots. When
the user corrects the target, version, or scope, update the task contract and
`sourceBinding`. Invalidate affected claims, preserve evidence that still applies,
stop superseded lanes when possible, and collect necessary replacement evidence
within the updated authorization. Check any late results against the current
binding before using them. Continue in the same task; a user correction alone
does not invalidate unrelated evidence or require a new run.

Add questions or lanes when evidence reveals a material need within scope.
Estimates are adjustable; explicit user and host limits remain binding. A lane
may be retried once after a transient transport or service failure. Correcting
result format, requesting necessary missing information, or researching an
updated binding is not such a retry and grants no additional authority or budget.
Stop when evidence is sufficient, further retrieval has no material expected
benefit, or a hard limit or genuine blocker prevents further work. Record
remaining gaps and work outside authorized scope or hard limits.

## Record sources and claims

Authority is claim-specific:

- user intent and scope trace to the restated request above;
- current project behavior traces to the bound source, configuration, tests as
  text, history, or canonical project documentation;
- third-party behavior traces to primary material for the project's actual
  version and deployment mode;
- practice claims need evidence independent of the target vendor or maintainer —
  a mirror, syndication, or common upstream material is not independent
  corroboration.

For each decisive source, record only:

- a direct URL or project-relative locator, specific enough to reopen (a
  section, anchor, page, symbol, release, or commit when the source is long);
- one line stating what it establishes and which question(s) it answers;
- a caveat instead, when the source is likely to have moved on by the time this
  is read (a mutable "latest" page, an evolving thread) — note that in prose; no
  separate freshness-tracking record is needed.

Give every decision-relevant factual claim about the project or an external
source at least one opened, reopenable source next to it. An inference names its
supporting facts and assumptions inline. A recommendation names its supporting
facts or inferences, rationale, affected scope, and tradeoffs — in prose, next to
the recommendation, not in a separate table. Record inaccessible primary
material, version skew, contradictions, and unsupported assertions as gaps,
conflicts, or drift.

Never record or return secrets or credentials. Prefer locators and paraphrases.
Use private code or personal data only as a minimum authorized sanitized excerpt
when its wording is necessary to a decision.

## Assess lane results

Each result must establish its answer, the opened sources and claims they
support, applicability to its assigned target and version, searched coverage,
and any material unsearched scope, conflicts, or gaps. Keep the answer within
the lane's question; workers do not make cross-lane judgments or requirements.
Use concise prose or structured fields as appropriate. Empty placeholders and
fixed field names are not required.

The coordinator may normalize lane identity, source-binding snapshots, and
dispatch metadata from actual records, or request necessary missing information.
Do not invent sources, coverage, facts, or compliance with instructions, and do
not treat worker confidence as verification. Missing non-substantive metadata
such as `budgetUsed` or `attempts` does not invalidate adequate evidence or
prevent completion. When a limit or applicability decision depends on missing
information, resolve it or report the resulting material gap. Format
clarification does not count as a transient-failure retry.

Only the current main-session coordinator reconciles sources and synthesizes
the requirements analysis. Reopen evidence when its support, locator, or
applicability remains unresolved.

## Build and classify the ResearchBrief

Keep these fields in conversation:

- the `ResearchContract`, including revised estimates, and actual execution route;
- valid lane results, their sources, and the facts, inferences, and
  recommendations they support;
- `conflicts`, `gaps`, `searched`, `unsearched`, and meaningful limitations;
- requirement implications and decisions still owned by the user;
- aggregate `status` using the rules below.

Classify aggregate status as:

- `complete`: every material research question has adequate opened, applicable, and
  non-invalidated evidence;
- `partial`: stable useful evidence supports some analysis, but a material gap,
  conflict, or explicit user or host limit prevents complete coverage;
- `blocked`: unresolved target identity, authority, access, or required evidence
  prevents any evidence-backed requirements analysis;
- `drifted`: a changed target binding or decisive source still invalidates the
  analysis and cannot be resolved within the current task's authority and limits.

Do not report `complete` when a decisive source has unresolved drift or a
material conflict or gap remains. Format omissions and resolved user corrections
are not completion failures; assess coverage against the current task contract.

## Attribute each requirement

For each supported requirement, state it with an observable acceptance
criterion, and tag it with exactly one authority source:

- **from the request:** directly authorized by what the user asked for or
  already accepted;
- **constraint:** a cited compatibility condition, or a governing obligation the
  user flagged as in scope, that limits how the accepted intent can be satisfied
  regardless of whether it was asked for;
- **suggestion:** an evidence-supported recommendation that remains unaccepted
  until the user decides.

Link each requirement to its supporting source(s) or to the restated request
directly above it — a separate ID-cross-reference table is not needed. Project
evidence does not make the current design immutable; external evidence does not
prove user acceptance. A user may change scope to avoid an otherwise applicable
constraint, but the analysis must not label that condition a suggestion while the
current binding still establishes its applicability. State what is needed and
how success is observed without prematurely fixing an implementation.

## Deliver by overall status

Start every answer with `Overall status: complete|partial|blocked|drifted` and use
only the matching branch:

- **complete:** lead with the proposed outcome, then the relevant request basis,
  supported requirements, acceptance criteria, sources, material alternatives,
  and any non-material limitations;
- **partial:** label the outcome provisional, include only requirements
  supported by stable evidence, and identify coverage gaps, affected
  conclusions, unsearched scope, and the smallest next action;
- **blocked:** do not emit requirements; identify the exact missing identity,
  authority, access, or evidence and the smallest user or environment action that
  would unblock analysis;
- **drifted:** do not present invalidated requirements as current; identify the
  changed binding or source, affected claims, and the exact authority, access,
  evidence, or environment change needed to resume the unresolved research.

For every branch, preserve material assumptions and conflicts, place citations
next to supported claims, omit empty boilerplate, and distinguish user-owned
decisions from evidence. Do not initiate a GOAL, documentation, review,
verification, or implementation workflow.
