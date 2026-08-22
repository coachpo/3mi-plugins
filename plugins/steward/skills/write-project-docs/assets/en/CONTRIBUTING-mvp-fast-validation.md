### MVP Fast Validation

This phase targets validating the confirmed core assumptions, scope, non-goals, and observable acceptance and exit conditions in [`{{PRODUCT_DOC}}`]({{PRODUCT_DOC}}), prioritizing the smallest observable end-to-end loop that produces usable evidence. "Shortest" means the shortest path to trustworthy feedback, not the fewest lines of code, steps, or tests.

This subsection is the enabled-MVP scope overlay for the "General Design Principles" and "General Implementation Principles": include only work that directly serves the core validation above, without expanding scope for completeness.

**Explicitly out of scope:** security or privacy governance, permission-system expansion, data-integrity enhancements, compatibility-layer construction and full compatibility regression, dedicated reachable-risk governance, repository-wide full checks, and production hardening that are unrelated to the core assumptions, observable acceptance conditions, and exit conditions, together with additional features and non-primary business branches that do not affect the current conclusion. Existing compatibility commitments and repository-required checks are not themselves in this category and do not authorize exclusion; only their non-core specialized implementation, full validation, or default gates may be excluded. Existing compatibility commitments still constrain solution choice, and checks required for affected paths or core acceptance still run.

**May be deferred:** work that does not currently affect the conclusion but must return when observable triggers arise, such as real users, real or non-discardable data, external traffic, compatibility acceptance, the corresponding risk, or another observable condition. Every item must state the work, the current basis for deferral, and at least one observable re-evaluation trigger. An item without such a trigger that is unrelated to core validation is explicitly out of scope; an item that affects the current conclusion belongs in the current loop.

**Still constraints:**

- Do not widen permissions.
- Do not perform unauthorized external writes.
- Do not perform unauthorized destructive operations.
- Do not delete or reset existing data.
- Do not fabricate validation results.
- Do not intentionally violate explicit prohibitions in [`STATUS.md`](STATUS.md).

These constraints limit available actions without automatically adding specialized implementation or full checks.

Within that narrowed scope, design and implementation still follow their respective ordering above. When several options can complete the core validation, prefer the one with the smallest change surface, the fewest new dependencies, and the easiest observation and rollback. Local, low-risk, reversible implementation details that do not change authorization boundaries may be decided directly within existing authority and the established development workflow.

Implement only what the current validation requires; do not add generalized capabilities, abstractions, or dependencies for unvalidated requirements. Run the narrow validation needed to make the conclusion observable and reproducible. Non-core repository-wide full checks, default gates, and production hardening are not completion prerequisites, but checks explicitly required for affected paths or core acceptance still run. Do not present an unaccepted validation implementation as formal architecture or production capability.
