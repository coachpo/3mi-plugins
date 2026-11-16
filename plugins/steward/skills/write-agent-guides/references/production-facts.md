# Production Facts

State these facts inline in the root `AGENTS.md` when documenting deployment
there is within the authorized fact scope. They
decide whether an agent may discard data, rewrite migrations, or pass a secret
directly, so a link alone is not enough; also link the project status document
when one records them.

## Deployment status

State whether the project has a production deployment, decided by the
deployment-status rule in the default policies that `SKILL.md` links. Report
any conflict with the existing migration rule; do not change that rule
without explicit policy authorization.

## Production identifiers

For a project with a production deployment, list what identifies production or
real accounts:

- Databases and other data stores, by name, instance, or the variable that
  holds the connection string.
- Deployment targets: account, project, service, or worker names.
- Branches that trigger a production deployment.
- Production domains.
- Production or real-account secrets, by variable or file name only. Never
  write a secret value.

Take each entry from verified configuration, CI, existing documents, or the
user's statement, and mark an entry that remains unverified. Omit the list for
a project with no production deployment.

Do not present the verified list as exhaustive. How to classify unlisted
targets is policy, not a deployment fact.
