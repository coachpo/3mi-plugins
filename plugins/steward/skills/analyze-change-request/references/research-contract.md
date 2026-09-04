# Change-request research contract

Use this reference to freeze the analysis contract, validate lane results, and
write the final answer. The structures are answer-local and conversational; they
do not authorize a file write or create project authority.

## Freeze the ResearchContract

Record all fields before evidence collection:

- `requestRaw`: the request as given, plus a plain-language restatement of what
  the user is asking for and has already accepted (outcome, included/excluded
  scope, constraints, priorities, and prior approvals). No ID scheme is needed —
  keep it in your own words and point back to it directly when you rely on it;
- target, exact `targetRoot` when repository evidence applies, actors,
  environment, constraints, assumptions, `include`, and `exclude`;
- `sourceBinding`: revision, installed versions, deployment mode, jurisdiction,
  and research `asOf` date that materially affect applicability;
- required `applicableInstructions`: the lane-relevant user constraints and
  applicable `AGENTS.md` sources and rules, or `none-found`; never copy hidden
  host, system, or developer text;
- material `researchQuestions` with stable question IDs;
- `frozenLanes`, each mapped to question IDs and one capability class;
- `evidenceBudget`: finite task-wide and per-lane query, source, time, and
  concurrency limits appropriate to the request;
- `retryLimit: 1` for a transient transport or service failure and a terminal
  stopping condition.

Do not turn an assumption, repository behavior, or external recommendation into
part of what the user asked for or already accepted.

After the first search or worker dispatch, the questions, lanes, scope, capability
classes, and budgets are immutable. Put any newly discovered need in `gaps` or
`unsearched`; do not expand the run.

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

## Require the LaneResult schema

Every worker returns every field below; use an empty list or explicit `none` when
there is no value. A prose summary or arbitrary subset is invalid.

- `laneId` and `laneKind`: `repository`, `official`, or `practice`;
- `status`: `complete`, `partial`, `blocked`, or `drifted`;
- `questionIds`, sanitized `sourceBinding`, and
  `applicableInstructionsApplied`;
- `directAnswer`, without cross-lane judgment or requirements;
- `sources`: the link/locator plus one-line takeaway from above, one per
  decisive source;
- `searched`, `unsearched`, `conflicts`, and `gaps`;
- `budgetUsed`, `stopReason`, and `attempts` (`1` or `2`; attempt two requires a
  recorded transient failure).

Only the current main-session coordinator may reject malformed results, reopen
decisive evidence, reconcile sources, and synthesize the answer. It must not infer
missing required fields or treat worker confidence as verification.

## Build and classify the ResearchBrief

Keep these fields in conversation:

- the frozen `ResearchContract` and actual execution route;
- valid lane results, their sources, and the facts, inferences, and
  recommendations they support;
- `conflicts`, `gaps`, `searched`, `unsearched`, and meaningful limitations;
- requirement implications and decisions still owned by the user;
- aggregate `status` using the rules below.

Classify aggregate status as:

- `complete`: every material frozen question has adequate opened, applicable, and
  non-invalidated evidence;
- `partial`: stable useful evidence supports some analysis, but a declared gap,
  conflict, failed lane, or budget limit prevents complete coverage;
- `blocked`: unresolved target identity, authority, access, or required evidence
  prevents any evidence-backed requirements analysis;
- `drifted`: the frozen target binding or decisive evidence changed enough to
  invalidate the analysis.

Do not report `complete` when a required lane result is malformed, a decisive
source has unresolved drift, or a material conflict or gap remains.

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
constraint, but the analysis must not label that condition a suggestion while its
applicability remains frozen. State what is needed and how success is observed
without prematurely fixing an implementation.

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
  changed binding or source, affected claims, and the smallest rebind and research
  needed for a new run.

For every branch, preserve material assumptions and conflicts, place citations
next to supported claims, omit empty boilerplate, and distinguish user-owned
decisions from evidence. Do not initiate a GOAL, documentation, review,
verification, or implementation workflow.
