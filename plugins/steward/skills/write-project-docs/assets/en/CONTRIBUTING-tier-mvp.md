## Current Development Strategy

**Development tier: `MVP`**

Complete the smallest observable end-to-end loop around the confirmed core value, scope, non-goals, acceptance conditions, and exit conditions in [`{{PRODUCT_DOC}}`]({{PRODUCT_DOC}}).

### Must Complete at This Tier

- Complete the core user flow, visible result, and error paths directly required by core acceptance.
- Run affected-path tests, checks, and builds sufficient to make the core conclusion observable and repeatable.
- Apply necessary controls to reachable authentication, authorization, privacy, data-integrity, compatibility, and irreversible-state boundaries.

### Not Pursued by Default

- Do not pursue non-core features, dedicated security or privacy programs, permission-system expansion, compatibility layers and full compatibility regression, repository-wide default gates, high availability, or production hardening.
- Do not add general capabilities, abstractions, dependencies, or non-primary business branches for unverified needs.

### Non-negotiable Boundaries

- Existing compatibility commitments, repository-required checks, and explicit prohibitions in [`STATUS.md`](STATUS.md) remain effective.
- Do not widen permissions, perform unauthorized external writes or destructive operations, delete or reset existing data, or fabricate validation results.

### Tier Transition Conditions

- Move to `PILOT` when limited real users, real or non-discardable data, external traffic, or pilot operating responsibility appears.
- Move to `PRODUCTION` when general availability, explicit SLOs, or sustained production support is required.
