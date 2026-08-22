# Source Code Size and Responsibility Rules

## Purpose

These rules constrain the responsibility boundaries and maintainable size of hand-written source code, helping developers and coding agents preserve the existing architecture, avoid responsibility sprawl, and review structure proactively before a file keeps growing.

Line count triggers a review; it never delivers the verdict. Whether to split is decided by the responsibility self-check: a long file that passes may stay, and a short file that fails must still be split. Any split must improve responsibility, dependency direction, testability, or change isolation; never break cohesion just to satisfy a number.

Line counts in these rules are physical lines, as reported by ordinary tools such as `wc -l`. Because line count only decides when a review is triggered, no greater precision is needed.

## Scope

These rules apply to ordinary hand-written source files that carry business behavior, interaction behavior, state management, orchestration, adaptation, data access, or infrastructure behavior.

The following do not take the ordinary behavior-file size signals and self-check directly, but must still stay clear, reviewable, and compliant with the project architecture:

- Generated code that a deterministic process can regenerate;
- Database migrations and indivisible records of historical evolution;
- Schemas, protocols, catalogs, mapping tables, and other files that are primarily declarative data;
- Third-party or vendored code;
- Test snapshots, fixtures, and large test data;
- Integration tests kept cohesive by a complete narrative or end-to-end flow.

Do not evade these rules by disguising behavioral code as configuration, macros, callbacks, generated code, or data tables.

## Responsibility Self-Check

The self-check is the gate in these rules. None of the three questions requires understanding the full business logic — each can be answered from the file's header, its exported symbols, and its call relationships — and each one points directly at a split boundary when it fails.

**1. Can the responsibility be stated in a single phrase?**

Can the file's primary responsibility be stated as one noun phrase that uses no conjunction (`and`, `or`) and does not lean on vague words such as `utils`, `helpers`, `common`, `core`, `base`, `manager`, or `misc`?

Split boundary when it fails: if a conjunction is required, each side of it is a separate responsibility — split there. If only a vague word fits, the file has no responsibility yet; move its symbols into the modules that actually own them.

**2. Do the dependencies stay within their permitted layers?**

Do the file's imports cross only the layers permitted by `{{ARCHITECTURE_DOC}}`? A file that directly depends on a transport framework, a persistence implementation, domain models, and an external SDK at once has already crossed layers, however short it is.

Split boundary when it fails: the out-of-layer dependencies and the code that calls them are what must be extracted — into the permitted layer, or into a new module with an explicit interface.

**3. Is the export surface cohesive?**

Do the caller sets of the file's exported symbols overlap? If the callers of symbol A and symbol B are entirely disjoint, the two do not belong to the same responsibility.

Split boundary when it fails: group the exported symbols by caller set; each disjoint group is a split boundary.

If a file cannot pass one of these questions for a verifiable structural reason over the long term, record that exception and its rationale in `{{ARCHITECTURE_DOC}}`; an exception must not rewrite these general rules.

## Size Review Signals

- When a file reaches about 240 lines, review its primary responsibility, dependency direction, and natural split boundaries early, so it does not swell passively under later requirements.
- When an ordinary hand-written behavior file exceeds 300 lines, run the responsibility self-check. Passing all three questions is enough to continue, with no added justification in the change description; failing any question means splitting along the boundary that question identifies.
- When a function or method reaches about 50 lines, check whether it mixes several phases, abstraction layers, error-handling strategies, or side effects. To keep a longer function, you must be able to explain its continuity and its testable boundary.

These numbers decide only when a review is triggered, never whether to split. The logical density they correspond to varies widely across languages, so they must not be enforced as caps.

## Responsibility and Splitting Principles

- Every file should have one clearly stateable primary responsibility and one primary reason to change.
- Split along domain boundaries, module boundaries, state lifecycles, input/output boundaries, or side-effect boundaries.
- Entry points, composition roots, and routing layers stay thin, mainly handling assembly, dispatch, and boundary conversion; do not impose a uniform line limit on them that is detached from project facts.
- New responsibilities belong in the correct existing module, or in a new module with an explicit interface; convenience of access is never a placement reason.
- Extraction should reduce cognitive load and preserve or improve dependency direction, naming, tests, and error handling.

The following mechanical splits are prohibited:

- Cutting by line count into `part1`, `part2`, or sibling files with unclear meaning;
- Collecting unrelated logic into a generic `utils`, `helpers`, or "common" module;
- Adding pass-through wrappers, proxy layers, or interfaces with no business meaning;
- Hiding complexity behind nested callbacks, macros, configuration, or generation steps;
- Moving code without forming a new responsibility boundary or test boundary.

## Legacy Large Files

- An existing large file does not become a refactoring target for unrelated changes because of its size alone.
- When modifying a legacy large file, do not keep adding new independent responsibilities to it.
- Change history is verifiable evidence when judging whether a natural split boundary exists: if one region of the file has never been modified together with the rest across recent commits, it carries an independent reason to change, and its extent is the split boundary.
- If a safe, natural, verifiable split boundary exists near the current change, extract that boundary first and run the applicable verification.
- If splitting would widen the scope, change behavior, or lack verification conditions, keep the current modification local and explain in the change description why it was not split; never use a sweeping incidental refactor to mask the current requirement.

## Coding Agent Requirements

Before starting to code:

1. Read `{{ARCHITECTURE_DOC}}`, `{{DEVELOPMENT_RULES_DOC}}`, and these rules;
2. Confirm the target module, the permitted dependency directions, and the existing implementation; a new file must have an explicit owning module in `{{ARCHITECTURE_DOC}}` — settle that placement before implementing;
3. Check the current size and responsibility of the files you plan to modify or add.

While coding:

1. Keep checking whether you have added an independent responsibility, crossed an architectural boundary, or duplicated an existing capability;
2. Split at natural boundaries as they appear, rather than handling it mechanically once the file is finished;
3. Keep entry points and composition code thin, leaving business rules in the modules that own them.

Before finishing:

1. Run the project's applicable tests, static checks, and build verification;
2. Run the responsibility self-check on every ordinary hand-written behavior file this change added or grew past 300 lines, and list the ones that fail; if there are none, say so explicitly;
3. For each listed file, give the split boundary you will apply, or explain why it stays local in this change (see Legacy Large Files);
4. Confirm that these rules were not evaded through mechanical splitting, meaningless abstraction, or hidden complexity.
