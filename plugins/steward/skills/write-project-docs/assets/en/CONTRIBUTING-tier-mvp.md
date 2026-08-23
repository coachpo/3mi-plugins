## Current Development Strategy

**Development tier: `MVP`**

Complete the smallest observable end-to-end loop around the confirmed core value, scope, non-goals, acceptance conditions, and exit conditions in [`{{PRODUCT_DOC}}`]({{PRODUCT_DOC}}). This tier permanently forgoes active investment in security, privacy, data, credential and key management, compatibility, audit/monitoring/SLO, and regulatory compliance requirements.

### Must Complete at This Tier

- Complete the core user flow, visible result, and error paths directly required by core acceptance.
- Run affected-path tests, checks, and builds sufficient to make the core conclusion observable and repeatable.

### Not Pursued by Default

- Permanently forgo active investment in security, privacy, data, credential and key management, permission-system expansion, compatibility layers and full compatibility regression, audit/monitoring/SLO, and regulatory compliance requirements; do not pursue non-core features, repository-wide default gates, high availability, or production hardening.
- Do not add general capabilities, abstractions, dependencies, or non-primary business branches for unverified needs.

### Non-negotiable Boundaries

- Explicit user requirements, an accepted GOAL, hard project rules or invariants, repository-required checks, and explicit prohibitions in [`STATUS.md`](STATUS.md) remain effective and are not affected by the exemption; existing compatibility commitments are existing contracts and are not deleted by this tier.
- Do not widen permissions, perform unauthorized external writes or destructive operations, delete or reset existing data, or fabricate validation results.

### Tier Transition Conditions

- Move to `PILOT` when limited real users, real or non-discardable data, external traffic, or pilot operating responsibility appears.
- Move to `PRODUCTION` when general availability, explicit SLOs, or sustained production support is required.
