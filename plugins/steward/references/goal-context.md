# GOAL context contract

Every GOAL bundle has exactly one immutable `context.md`. It contains verified
sources and useful background, not a second GOAL, authorization, completion
decision, digest, case result, or authoring-process narration.

Project sources use project-relative paths plus a symbol or section when useful.
External sources identify title, canonical URL, applicable version or section,
verification date, relationship to the GOAL, and a short supporting summary.
If no verified context remains, block instead of inventing content.

The file is UTF-8 without BOM or NUL, uses LF only, and ends with one LF. Its
canonical path is `.steward/goals/<alias>/context.md`; the GOAL references that
path exactly once in `证据与上下文`. Absolute paths stay in the private manifest
worktree binding, never in the GOAL or context.
