<!-- write-project-docs:document-navigation:start -->
## Project Documentation Navigation

Before starting related work, read the authoritative documents that cover the scope of the task:

- [Project Status](STATUS.md)
- [Documentation Index](docs/README.md)
- [Product Overview]({{PRODUCT_DOC}})
- [Architecture Overview]({{ARCHITECTURE_DOC}})
- [Development Rules]({{DEVELOPMENT_RULES_DOC}})
- [Source Code Size and Responsibility Rules]({{SOURCE_SIZE_RULES_DOC}})
- [Contributing Guide](CONTRIBUTING.md)

When implementing, reviewing, or verifying an engineering change, use `STATUS.md` and the product overview for current facts and delivery intent, then read the [Current Iteration Strategy](CONTRIBUTING.md#current-iteration-strategy) and "MVP Fast Validation" H3 when those sections exist. Consume only the required-now items, authorization boundaries, and re-derivation triggers relevant to the task. When MVP is enabled, apply its "Explicitly out of scope," "May be deferred," and "Still constraints" layers, retaining the current basis and observable re-evaluation trigger for every concrete deferred item. Existing compatibility commitments and repository-required checks are not themselves authorization to exclude work: only non-core specialized implementation, full validation, or default gates may be excluded, while checks required for affected paths or core acceptance still run. Re-include work when a new user requirement, active Goal, hard project rule or invariant, evidence invalidating the core conclusion, or a recorded re-evaluation trigger applies. The strategy and MVP switch remain independently stored, and neither expands user authorization; do not reuse a stale strategy after source facts or its digest change.

## Project Documentation Content Boundaries

This project does not add process or administrative management for the sake of documentation completeness.

- Unless the user explicitly asks and provides verifiable evidence, do not add approvals, reporting, meetings, scheduling, personnel governance, release governance, commit management, business KPIs/SLOs, or similar content.
- Do not create documents, sections, placeholders, or "to be confirmed" items for those topics.
- Existing and verified development, test, build, and deployment commands remain recorded in their own authoritative documents; this block does not change product, architecture, or engineering facts.
<!-- write-project-docs:document-navigation:end -->
