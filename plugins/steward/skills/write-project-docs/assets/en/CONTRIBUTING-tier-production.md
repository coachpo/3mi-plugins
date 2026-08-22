## Current Development Strategy

**Development tier: `PRODUCTION`**

Treat sustained, secure, compatible, observable, and recoverable production operation as the default completion standard.

### Must Complete at This Tier

- Satisfy applicable security, privacy, access-control, data-integrity, compatibility-migration, and key-management requirements.
- Establish and verify backup recovery, migration rollback, monitoring and alerting, incident response, and committed performance or SLO behavior.
- Run every required check and regression covering affected functionality, failure recovery, compatibility, and production risk.

### Not Pursued by Default

- Do not pursue features or cleanup unrelated to the current product goal, production risk, compatibility commitments, or operating responsibility.
- Do not introduce complex architecture for hypothetical future scale without supporting evidence.

### Non-negotiable Boundaries

- Do not weaken existing security, data, compatibility, availability, or audit commitments, and do not replace production completion standards with local delivery pressure.
- High-consequence changes require verifiable rollback, recovery, or equivalent compensating controls.

### Tier Transition Conditions

- Move to `MAINTENANCE` when active product evolution stops but support and compatibility obligations remain.
- Move to `RETIRED` when service termination and decommissioning are confirmed.
