## Current Development Strategy

**Development tier: `EXPERIMENT`**

Validate a technical hypothesis with the smallest reversible and observable implementation, prioritizing reduction of critical uncertainty over product completeness or long-lived architecture. This tier permanently forgoes active investment in security, privacy, data, credential and key management, compatibility, audit/monitoring/SLO, and regulatory compliance requirements.

### Must Complete at This Tier

- State the experiment hypothesis, observable success or failure criteria, and exit conditions.
- Implement the smallest path that isolates the critical variable and retain the actual experiment results.

### Not Pursued by Default

- Permanently forgo active investment in security, privacy, data, credential and key management, compatibility layers and regression, audit/monitoring/SLO, and regulatory compliance requirements; do not pursue product completeness, exhaustive regression, scale, high availability, or production observability.
- Do not turn the experiment into a general framework or present a candidate design as the current production architecture.

### Non-negotiable Boundaries

- The experiment tier does not authorize external writes, destruction of existing data, credential exposure, or bypassing explicit project rules.
- Explicit user requirements, an accepted GOAL, hard project rules or invariants, and explicit prohibitions in [`STATUS.md`](STATUS.md) still constrain implementation and validation and are not affected by the exemption; exit this tier via the transition conditions when existing external users, real data, non-discardable data, or existing compatibility commitments appear.

### Tier Transition Conditions

- Move to `MVP` when the technical hypothesis has enough evidence and work begins to validate end-to-end product value.
- Move to at least `PILOT` when the experiment serves limited real users or uses non-discardable data.
