# Architecture profile selection evidence v1

The `select` command consumes one small repository-evidence document. Its
machine shape is defined by
[`selection-evidence-v1.schema.json`](selection-evidence-v1.schema.json); the
bundled Python validator is authoritative for safe normalized paths, ordering,
size limits, and exact fields.

```json
{
  "schemaVersion": 1,
  "components": [
    {
      "scope": "services/api",
      "signals": ["dependency:fastapi", "entry:asgi"],
      "capabilities": {
        "fastapi.async": "present",
        "fastapi.database": "unknown"
      }
    }
  ]
}
```

- `components` names unique project scopes. Use `.` only for the repository
  root; otherwise use a normalized project-relative POSIX path.
- `signals` are sorted repository facts used only for deterministic profile
  activation. A profile activates when one complete `allOf`/`anyOf` clause
  below matches and no `noneOf` signal matches. Supporting signals in a profile
  add evidence but never activate it alone.
- `capabilities` contains only tokens relevant to the selected profiles. Its
  keys are sorted, and each value is `present`, `absent`, or `unknown`. Missing
  capabilities are treated as `unknown`; never rewrite unknown evidence as
  absent.

## Activation signal vocabulary

| Profile | Activation clause |
| --- | --- |
| Android | all of `manifest:android`, `source:android` |
| Cloudflare Workers | any of `config:wrangler`, `runtime:cloudflare-worker` |
| Django | all of `dependency:django`, `entry:django` |
| FastAPI | all of `dependency:fastapi`, `entry:asgi` |
| Go | all of `manifest:go`, `source:go` |
| Python | all of `manifest:python`, `source:python` |
| Tauri 2 | all of `dependency:tauri2`, `manifest:cargo` |

The bundled profile JSON remains authoritative for activation clauses,
supporting signals, and capability tokens. Django and FastAPI automatically
extend Python; do not add Python signals merely to manufacture the base layer.

Run selection and compilation with the installed script path:

```text
python3 <skill-dir>/../../scripts/architecture_profiles.py select --evidence evidence.json --output selection.json
python3 <skill-dir>/../../scripts/architecture_profiles.py compile --selection selection.json --output compiled.json
```

The evidence, selection, and compiled artifacts all use schema v1, and the
compiler starts at version `1.0.0`. These commands compile data only.
They do not scan the repository, execute a profile check, or turn the resulting
artifact into project authorization.
