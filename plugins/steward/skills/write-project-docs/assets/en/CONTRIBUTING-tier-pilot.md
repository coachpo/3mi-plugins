## Current Development Strategy

**Development tier: `PILOT`**

Support limited real users and real feedback within a controlled scope while validating product, data, and operating flows with a recoverable implementation.

### Must Complete at This Tier

- Implement authentication, authorization, privacy, data-integrity, and necessary compatibility controls for actual user paths.
- Establish verifiable data migration, backup or rollback paths, plus logs, metrics, and alerts sufficient to diagnose pilot issues.
- Cover core flows, affected compatibility surfaces, primary failure modes, and recovery paths, and record pilot feedback conditions.

### Not Pursued by Default

- Do not build capacity, global high availability, multi-region recovery, or long-term scale optimization beyond pilot users and traffic.
- Do not expand features or platform capabilities unrelated to pilot goals, risks, or feedback.

### Non-negotiable Boundaries

- Limited pilot scope is not a reason to weaken protection of real users, real data, credentials, or reachable interfaces.
- Do not perform high-consequence migrations without rollback or recovery evidence, and do not violate existing compatibility or data commitments.

### Tier Transition Conditions

- When the pilot ends and real use stops, move to `MVP`, `MAINTENANCE`, or `RETIRED` according to the next objective.
- Move to `PRODUCTION` before general availability, sustained operation, or explicit SLO commitments.
