## Current Development Strategy

**Development tier: `EXPERIMENT`**

Validate a technical hypothesis with the smallest reversible and observable implementation, prioritizing reduction of critical uncertainty over product completeness or long-lived architecture.

### Must Complete at This Tier

- State the experiment hypothesis, observable success or failure criteria, and exit conditions.
- Implement the smallest path that isolates the critical variable and retain the actual experiment results.
- Protect any credentials, data, permissions, and external interfaces in proportion to their reachable risk.

### Not Pursued by Default

- Do not pursue product completeness, broad compatibility, exhaustive regression, scale, high availability, production observability, or dedicated security work unrelated to the experiment.
- Do not turn the experiment into a general framework or present a candidate design as the current production architecture.

### Non-negotiable Boundaries

- The experiment tier does not authorize external writes, destruction of existing data, credential exposure, or bypassing explicit project rules.
- Existing external users, real data, compatibility commitments, and reachable security risks still constrain implementation and validation.

### Tier Transition Conditions

- Move to `MVP` when the technical hypothesis has enough evidence and work begins to validate end-to-end product value.
- Move to at least `PILOT` when the experiment serves limited real users or uses non-discardable data.
