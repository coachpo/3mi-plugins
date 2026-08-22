#!/usr/bin/env python3
"""Read-only validator for the project invariant map and AGENTS router."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = SKILL_ROOT.parent.parent
for directory in (
    PLUGIN_ROOT / "scripts",
    SKILL_ROOT.parent / "write-project-docs" / "scripts",
):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from canonical_paths import resolve_project_docs
from invariant_contract import (
    INVARIANT_MAP_RELATIVE_PATH,
    ROUTER_END_MARKER,
    ROUTER_START_MARKER,
    InvariantContractError,
    find_invariant_map,
    load_invariant_map,
    validate_project_references,
)
from managed_blocks import (
    ManagedBlockError,
    locate_managed_block,
    visible_section_titles,
)
from update_engineering_router import (
    DOCUMENT_NAV_END_MARKER,
    DOCUMENT_NAV_START_MARKER,
    ROUTER_TITLES,
    detect_language,
    render_router,
)


def validate_engineering_router(
    project_root: Path,
    *,
    profiles_root: Path | None = None,
    language: str | None = None,
) -> list[str]:
    """Return invariant/router errors; absence of both is the legacy success path."""

    root = project_root.resolve()
    agents_path = root / "AGENTS.md"
    map_path = find_invariant_map(root)
    agents_text: str | None = None
    if agents_path.is_file() and not agents_path.is_symlink():
        try:
            with agents_path.open("r", encoding="utf-8", newline="") as handle:
                agents_text = handle.read()
        except (OSError, UnicodeError):
            return ["AGENTS.md is not readable UTF-8"]
    elif map_path is not None:
        return ["invariant map requires an existing regular root AGENTS.md"]

    span = None
    navigation_span = None
    if agents_text is not None:
        try:
            span = locate_managed_block(
                agents_text,
                ROUTER_START_MARKER,
                ROUTER_END_MARKER,
                "root AGENTS.md engineering router",
            )
            navigation_span = locate_managed_block(
                agents_text,
                DOCUMENT_NAV_START_MARKER,
                DOCUMENT_NAV_END_MARKER,
                "root AGENTS.md document navigation",
            )
        except ManagedBlockError as error:
            return [str(error)]
        if span is not None and navigation_span is not None:
            separated = (
                span.end <= navigation_span.start
                or navigation_span.end <= span.start
            )
            if not separated:
                return [
                    (
                        "root AGENTS.md engineering router and document navigation "
                        "must not overlap"
                    )
                ]
        if span is not None:
            outside = agents_text[: span.start] + agents_text[span.end :]
            if visible_section_titles(outside, ROUTER_TITLES):
                return [
                    (
                        "root AGENTS.md has a duplicate unowned "
                        "engineering-router heading"
                    )
                ]
    if map_path is None:
        if span is not None:
            return [
                f"engineering router exists without {INVARIANT_MAP_RELATIVE_PATH}"
            ]
        return []

    try:
        invariant_map = load_invariant_map(map_path, profiles_root)
        context = resolve_project_docs(root)
        if context.errors:
            raise InvariantContractError("; ".join(context.errors))
        allowed = {
            "STATUS.md",
            "CONTRIBUTING.md",
            context.selected["product"],
            context.selected["architecture"],
            context.selected["development_rules"],
            context.selected["source_size_rules"],
        }
        errors = validate_project_references(
            root, invariant_map, allowed_authorities=allowed
        )
        if errors:
            return errors
        expected = render_router(
            invariant_map, language or detect_language(root, None)
        )
    except (OSError, UnicodeError, InvariantContractError) as error:
        return [str(error)]
    if span is None or agents_text is None:
        return ["root AGENTS.md is missing the engineering router"]
    if agents_text[span.start : span.end] != expected:
        return ["root AGENTS.md engineering router has drifted from invariant map"]
    if agents_text.count(expected) != 1:
        return ["root AGENTS.md engineering router is duplicated"]
    return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--profiles-root")
    parser.add_argument("--language", choices=("zh", "en"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    if not root.is_dir():
        print(f"error: project root is not a directory: {root}")
        return 2
    errors = validate_engineering_router(
        root,
        profiles_root=Path(args.profiles_root) if args.profiles_root else None,
        language=args.language,
    )
    if errors:
        print("errors:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("engineering router validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
