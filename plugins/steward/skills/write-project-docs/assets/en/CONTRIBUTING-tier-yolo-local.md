## Current Development Strategy

**Development tier: `YOLO_LOCAL`**

Take the shortest path to the observable goal in [`{{PRODUCT_DOC}}`]({{PRODUCT_DOC}}), exclusively inside a disposable local workspace explicitly declared by the user. This tier permits aggressive local implementation choices but grants no host, account, or external-system authority. This tier permanently forgoes active investment in security, privacy, data, credential and key management, compatibility, audit/monitoring/SLO, and regulatory compliance requirements.

### Must Complete at This Tier

- Complete the smallest runnable loop for the current goal and produce at least one real, repeatable observation.
- Keep every modification and destructive effect inside the confirmed disposable workspace and temporary data.
- Run the minimum affected-path smoke verification needed to support the claimed result.

### Not Pursued by Default

- Permanently forgo active investment in security, privacy, data governance, credential and key management, permission systems, compatibility layers and regression, audit/monitoring/SLO, and regulatory compliance requirements; do not pursue full tests, repository-wide gates, long-lived documentation, performance work, high availability, or production hardening.
- Do not add abstractions, extension points, migrations, or general infrastructure for unverified requirements.

### Non-negotiable Boundaries

- Do not handle real, personal, production, or non-discardable data; use production credentials; or accept external users or traffic.
- Do not perform external writes, deployments, publishing, purchases, or third-party account changes.
- Do not damage files outside the workspace, the host environment, or state not explicitly declared disposable, and do not fabricate validation results.
- Explicit user requirements, an accepted GOAL, hard project rules or invariants, and explicit prohibitions in [`STATUS.md`](STATUS.md) remain effective and are not affected by the exemption; leave this tier via the transition conditions when real data, production credentials, external users, external traffic, or non-discardable state appears.

### Tier Transition Conditions

- Exit `YOLO_LOCAL` immediately when real data, production credentials, external users, external traffic, external side effects, or non-discardable state become necessary; select at least `EXPERIMENT` or a stricter tier.
- Move to `MVP` when the goal becomes product-value validation, and to `PILOT` before serving limited real users.
