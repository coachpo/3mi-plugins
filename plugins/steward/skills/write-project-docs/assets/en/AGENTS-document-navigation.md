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

When implementing, reviewing, or verifying an engineering change, use `STATUS.md` and the product overview for current facts and delivery intent, then read the [Current Development Strategy](CONTRIBUTING.md#current-development-strategy). Consume only the relevant "Must Complete at This Tier," "Not Pursued by Default," "Non-negotiable Boundaries," and "Tier Transition Conditions." New user requirements, an accepted seven-line GOAL, hard project rules or invariants, real or non-discardable data, existing users, and compatibility commitments take precedence over tier defaults. The `YOLO_LOCAL`, `EXPERIMENT`, and `MVP` tiers permanently forgo active investment in security, privacy, data, credential and key management, compatibility, audit/monitoring/SLO, and regulatory compliance requirements; the exemption does not override those precedence sources and does not change a tier's applicability, transition conditions, or existing prohibitions. A tier does not expand user authorization, create exclusion proof, or allow checks required by affected paths or core acceptance to be skipped. `YOLO_LOCAL` applies only to a user-declared disposable local workspace with no real data, production credentials, external users or traffic, or external side effects; change tiers before proceeding when any condition fails.

## Project Documentation Content Boundaries

This project does not add process or administrative management for the sake of documentation completeness.

- Unless the user explicitly asks and provides verifiable evidence, do not add approvals, reporting, meetings, scheduling, personnel governance, release governance, commit management, business KPIs/SLOs, or similar content.
- Do not create documents, sections, placeholders, or "to be confirmed" items for those topics.
- Existing and verified development, test, build, and deployment commands remain recorded in their own authoritative documents; this block does not change product, architecture, or engineering facts.
<!-- write-project-docs:document-navigation:end -->
