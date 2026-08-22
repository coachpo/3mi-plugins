## Current Development Strategy

**Development tier: `RETIRED`**

Stop ordinary feature development and make safe, verifiable termination of service, access, credentials, and data responsibilities the only delivery direction.

### Must Complete at This Tier

- Close or isolate every entry point, background job, integration, and still-reachable runtime surface.
- Revoke credentials and permissions, and export, retain, migrate, or delete data according to authoritative policy.
- Verify decommissioning outcomes, residual dependencies, user communications, and required audit evidence.

### Not Pursued by Default

- Do not build new features or perform performance work, architecture rewrites, or platform expansion unrelated to decommissioning.
- Do not retain compatibility layers, credentials, data copies, or runtime resources without an explicit remaining obligation.

### Non-negotiable Boundaries

- Every interface, dataset, credential, and user path that remains reachable continues to satisfy applicable security, privacy, and compatibility requirements.
- Do not delete non-discardable data without authority, retention policy, and recovery evidence.

### Tier Transition Conditions

- Return to `EXPERIMENT`, `MVP`, `PILOT`, or `PRODUCTION` only after product goals, user responsibilities, and operating boundaries are reconfirmed.
- After all entry points, credentials, data responsibilities, and support commitments are closed, remain `RETIRED` and stop engineering changes.
