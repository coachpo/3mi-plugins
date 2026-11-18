# Persisted Data Cleanup

These criteria supplement the preservation obligations in
[simplify-repository](../SKILL.md).

- Enumerate all write sites for the stored field or variant. If writes produce
  only constant values or never write it, treat readers for values that cannot
  arise on new data as existing-data paths. Check whether the affected data
  can be discarded. Name any discardability fact the repository cannot
  establish and group the candidates that depend on it.
- Classify each candidate as removable, historical-looking but still live, or
  unresolved. Judge reachability, not labels: a legacy-named variant can still
  be written, and an ordinary null branch can serve only existing data.
- When removal is authorized and the change yields a net maintenance benefit,
  make the retired state unrepresentable in the affected types, validation, and
  storage constraints rather than deleting only the reader branch.
- If cleanup changes accepted persisted shapes, identify what would no longer
  be accepted and which existing data would become invalid. Stop the affected
  change if any data it would invalidate must be retained or its discardability
  is unresolved. Authorization to tighten new inputs does not authorize
  invalidating existing data. Discardable old data does not waive the
  [current-contract boundary](../SKILL.md#establish-scope-and-authority)
  or grant migration or deployment permission. Rebuilds, migrations, imports,
  releases, and deployments are outside this skill's scope.
