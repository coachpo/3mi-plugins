# Change-request research contract

Use this reference to freeze the analysis contract, validate lane results, and
write the final answer. The structures are answer-local and conversational; they
do not authorize a file write or create project authority.

## Freeze the ResearchContract

Record all fields before evidence collection:

- `requestRaw` and consecutive `intentRecords` with IDs `U1`, `U2`, and so on;
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

Each `U*` intent record contains `intentId`, the user's authorized statement,
`kind` (`outcome`, `include`, `exclude`, `constraint`, `priority`, or `approval`),
and `origin` (`current-request` or `accepted-user-decision`). Do not turn an
assumption, repository behavior, or external recommendation into a `U*` record.

After the first search or worker dispatch, the questions, lanes, scope, capability
classes, and budgets are immutable. Put any newly discovered need in `gaps` or
`unsearched`; do not expand the run.

## Classify sources and claims

Authority is claim-specific:

- user intent and scope trace to `U*` records;
- current project behavior traces to the bound source, configuration, tests as
  text, history, or canonical project documentation;
- third-party behavior traces to primary material for the project's actual
  version and deployment mode;
- legal, regulatory, or interoperability obligations trace to the applicable
  governing text or normative standard;
- practice claims require comparable evidence independent of the target vendor or
  maintainer. Mirrors, syndication, and common upstream material are not
  independent corroboration.

Each decisive source record contains:

- `sourceId`, title, publisher, source kind, and direct URL or project-relative
  locator;
- exact section, anchor, page, line, symbol, release, or commit locator;
- version, edition, document status, deployment context, jurisdiction,
  publication/update date, and `accessedAt` when applicable;
- `authority`: its claim-specific role, such as `project-state`,
  `official-product-behavior`, `governing-obligation`, or `practice-evidence`;
- `independence`: `first-party`, `independent`, `shared-origin`, or `unknown`, with
  the relevant relationship recorded;
- `normative`: `binding`, `normative-standard`, `official-guidance`,
  `non-normative`, or `unknown`;
- `drift`: the initially observed immutable revision or tag, or an `ETag`,
  `Last-Modified`, or content digest when the tool exposes one; recheck time;
  `stable`, `mutable`, `changed`, or `unknown`; and the effect of any change;
- exact supported claim IDs and support type `direct` or `inferred`.

Use `official-guidance`, `cross-source-convergence`, `community-practice`, or
`conflicted` only as synthesis labels. A publisher name alone does not establish
authority, independence, normative force, currency, or applicability.

Give every decision-relevant factual claim about the project or an external
source a claim ID and at least one opened source. An inference names supporting
claim IDs and assumptions. A recommendation names its supporting claims or
inferences, rationale, affected scope, and tradeoffs. User intent traces to `U*`
rather than an external citation. Record inaccessible primary material, mutable
`latest` pages, version skew, contradictions, and unsupported assertions as gaps,
conflicts, or drift.

A mutable decisive source without a comparable initial and final identity cannot
support aggregate `complete`; preserve it as a freshness gap and use `partial`.
Never replace the initial observation silently during the final recheck.

Never record or return secrets or credentials. Prefer locators and paraphrases.
Use private code or personal data only as a minimum authorized sanitized excerpt
when its wording is necessary to a decision.

## Require the LaneResult schema

Every worker returns every field below; use an empty list or explicit `none` when
there is no value. A prose summary or arbitrary subset is invalid.

- `laneId` and `laneKind`: `repository`, `official`, `obligation`, or `practice`;
- `status`: `complete`, `partial`, `blocked`, or `drifted`;
- `questionIds`, sanitized `sourceBinding`, and
  `applicableInstructionsApplied`;
- `directAnswer`, without cross-lane judgment or candidate `R*` requirements;
- `sources` using the complete source-record schema;
- claim-level `facts`, `inferences`, and `recommendations`;
- `searched`, `unsearched`, `conflicts`, and `gaps`;
- `budgetUsed`, `stopReason`, and `attempts` (`1` or `2`; attempt two requires a
  recorded transient failure);
- `execution`: route, allowed capability class, mechanical enforcement, and tool
  or worker limitations.

Only the current main-session coordinator may reject malformed results, reopen
decisive evidence, reconcile sources, and synthesize the answer. It must not infer
missing required fields or treat worker confidence as verification.

## Build and classify the ResearchBrief

Keep these fields in conversation:

- the frozen `ResearchContract` and actual execution route;
- valid lane results and claim-level sources, facts, inferences, and
  recommendations;
- `conflicts`, `gaps`, `searched`, `unsearched`, and meaningful limitations;
- `candidateRequirementImplications` and decisions still owned by the user;
- aggregate `status` using the rules below.

Classify aggregate status as:

- `complete`: every material frozen question has adequate opened, applicable, and
  non-invalidated evidence;
- `partial`: stable useful evidence supports some analysis, but a declared gap,
  conflict, failed lane, or budget limit prevents complete coverage;
- `blocked`: unresolved target identity, authority, access, or required evidence
  prevents any evidence-backed candidate analysis;
- `drifted`: the frozen target binding or decisive evidence changed enough to
  invalidate the candidate analysis.

Do not report `complete` when a required lane result is malformed, a decisive
source has unresolved drift, or a material conflict or gap remains.

## Classify candidate requirements

For each supported candidate, assign consecutive answer-local IDs `R1`, `R2`, and
so on. Each record contains the requirement, observable acceptance criteria,
traceability, and exactly one `authorityCategory`:

- `intent-derived`: directly authorized by one or more `U*` records;
- `binding-if-applicable`: a cited governing obligation or normative standard that
  binds the frozen jurisdiction and environment while they remain in scope;
- `compatibility-constraint`: a cited project, user, version, protocol, or external
  compatibility condition that constrains ways to satisfy the accepted intent;
- `optional`: an evidence-supported recommendation that remains unaccepted until
  the user decides.

Trace every `R*` to its supporting `U*`, claim, inference, or recommendation IDs.
Project evidence does not make the current design immutable; external evidence
does not prove user acceptance. A user may change scope to avoid an otherwise
applicable obligation or compatibility condition, but the analysis must not label
that condition optional while its applicability remains frozen. State what is
needed and how success is observed without prematurely fixing an implementation.

## Deliver by overall status

Start every answer with `Overall status: complete|partial|blocked|drifted` and use
only the matching branch:

- **complete:** lead with the proposed outcome, then the relevant `U*` basis,
  supported `R*` candidates, acceptance criteria, traceability, material
  alternatives, and any non-material limitations;
- **partial:** label the outcome provisional, include only candidates supported by
  stable evidence, and identify coverage gaps, affected conclusions, unsearched
  scope, and the smallest next action;
- **blocked:** do not emit `R*` candidates; identify the exact missing identity,
  authority, access, or evidence and the smallest user or environment action that
  would unblock analysis;
- **drifted:** do not present invalidated candidates as current; identify the
  changed binding or source, affected claims, and the smallest rebind and research
  needed for a new run.

For every branch, preserve material assumptions and conflicts, place citations
next to supported claims, omit empty boilerplate, and distinguish user-owned
decisions from evidence. Do not initiate a GOAL, documentation, review,
verification, or implementation workflow.
