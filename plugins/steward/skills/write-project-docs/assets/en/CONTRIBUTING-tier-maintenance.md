## Current Development Strategy

**Development tier: `MAINTENANCE`**

Preserve existing behavior, compatibility commitments, and operational stability, prioritizing defect, security, and necessary dependency fixes.

### Must Complete at This Tier

- Use the smallest change that satisfies the repair objective while preserving supported interfaces, data, and deployment compatibility.
- Run targeted verification for affected paths, reported defects, security boundaries, and regression risks.
- Synchronize required support notes, migration information, and authoritative documentation facts.

### Not Pursued by Default

- Do not add new features, rewrite architecture, perform broad refactors, or add dependencies unrelated to the maintenance objective.
- Do not expand the support matrix, compatibility surface, or operating responsibility unless an existing commitment or explicit requirement demands it.

### Non-negotiable Boundaries

- Maintenance mode is not a reason to defer known high-impact security issues, data-corruption risks, or regressions affecting existing users.
- Do not break supported interfaces, configuration, data schemas, or upgrade paths.

### Tier Transition Conditions

- Move to `PILOT` or `PRODUCTION` when product feature development resumes or the real-user scope expands.
- Move to `RETIRED` when support obligations end and service shutdown begins.
