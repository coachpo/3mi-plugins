<!-- write-project-docs:shared-contributing:start -->
## General Design Principles

While satisfying the confirmed functional scope, architectural boundaries, quality attributes, security, compatibility, and runtime constraints, choose a design in this order:

1. Existing, verified, and still-applicable designs, patterns, interfaces, or components already in the project;
2. Applicable formal standards, standard protocols, and officially recommended platform or framework solutions;
3. Mature industry solutions that are widely adopted in similar scenarios, actively maintained, and backed by reliable evidence of practice;
4. Only when none of the above satisfies a verified constraint, the smallest custom design that meets the current requirement.

"Widely used" is a candidate signal, not sufficient reason to adopt. Before adopting, check requirement fit, security and compatibility, primary failure modes, and maintenance and migration cost against the risk. Do not introduce capabilities, abstractions, or dependencies outside the current scope merely to follow a convention.

For significant design choices that touch architectural boundaries, dependency direction, data ownership, security boundaries, or long-lived dependencies, record the applicable rationale, the primary trade-offs, and the verification method in the design outcome. When adopting a custom design, also state the verified constraints that make mature solutions inapplicable. When risk is high and evidence is thin, first define observable success, failure, and exit conditions, then run the smallest reversible validation your current authority allows. Do not write unaccepted or unimplemented candidates into the record as current architectural fact.

## General Implementation Principles

While satisfying functional scope, architectural boundaries, correctness, security, and verifiability, choose an implementation in this order:

1. Existing implementations in the project;
2. The language standard library;
3. Platform-native capabilities;
4. Dependencies already installed in the project that fit the current scenario;
5. Mature, actively maintained, widely used third-party libraries suited to the current environment;
6. The smallest custom implementation that meets the current requirement.

Search for an existing implementation before adding new code. Do not pull in a large dependency for a small feature; do not create abstraction, extension, or compatibility layers for hypothetical future requirements; keep custom implementations local, simple, and testable.

Implementations must comply with the project architecture facts in [`{{ARCHITECTURE_DOC}}`]({{ARCHITECTURE_DOC}}), the project- and technology-specific rules in [`{{DEVELOPMENT_RULES_DOC}}`]({{DEVELOPMENT_RULES_DOC}}), and the unified size and responsibility rules in [`{{SOURCE_SIZE_RULES_DOC}}`]({{SOURCE_SIZE_RULES_DOC}}).

## Definition of Done

A change is complete only when all of the following hold:

- The implementation matches the confirmed functional scope and acceptance conditions;
- Significant design choices have been checked against the applicability of mature solutions; where a custom solution was adopted, the inapplicable constraints, primary trade-offs, and verification method are recorded;
- Existing architectural boundaries and dependency direction are preserved, with no unrelated responsibilities or incidental changes added;
- Applicable project- and technology-specific development rules are satisfied;
- Relevant tests, static checks, format checks, and build verification pass;
- The single authoritative documents, machine contracts, and validation are synchronized as required by the development rules;
- No secrets, credentials, personal data, build artifacts, or unrelated files are committed;
- The source code size and responsibility rules have been applied, and any long files that need explanation are reported.
<!-- write-project-docs:shared-contributing:end -->
