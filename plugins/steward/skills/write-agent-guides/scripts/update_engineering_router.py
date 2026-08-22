#!/usr/bin/env python3
"""Update the invariant-derived engineering router in an existing root AGENTS.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = SKILL_ROOT.parent.parent
SHARED_SCRIPTS = PLUGIN_ROOT / "scripts"
PROJECT_DOCS_SCRIPTS = SKILL_ROOT.parent / "write-project-docs" / "scripts"
for script_directory in (SHARED_SCRIPTS, PROJECT_DOCS_SCRIPTS):
    if str(script_directory) not in sys.path:
        sys.path.insert(0, str(script_directory))

from canonical_paths import resolve_project_docs
from invariant_contract import (
    INVARIANT_MAP_RELATIVE_PATH,
    ROUTER_END_MARKER,
    ROUTER_START_MARKER,
    InvariantContractError,
    ProfileSource,
    find_invariant_map,
    load_invariant_map,
    router_rows,
    validate_project_references,
)
from managed_blocks import (
    ManagedBlockError,
    locate_all_managed_blocks,
    locate_managed_block,
    visible_section_titles,
)
from safe_write import AtomicWriteCommittedError, read_snapshot, write_atomically
from update_agents_navigation import (
    END_MARKER as DOCUMENT_NAV_END_MARKER,
)
from update_agents_navigation import (
    START_MARKER as DOCUMENT_NAV_START_MARKER,
)

ROUTER_TITLES = ("Engineering Router", "工程路由")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update the invariant-derived engineering router in root AGENTS.md."
    )
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--profiles-root")
    parser.add_argument("--language", choices=("zh", "en"))
    return parser.parse_args()


def detect_language(root: Path, explicit: str | None) -> str:
    context = resolve_project_docs(root)
    if context.errors:
        raise InvariantContractError("; ".join(context.errors))
    resolved = context.language.value
    if explicit is not None and explicit != resolved:
        raise InvariantContractError(
            f"router language {explicit} conflicts with canonical document "
            f"language {resolved}"
        )
    return resolved


def router_asset_path(language: str) -> Path:
    if language == "zh":
        return SKILL_ROOT / "assets" / "zh" / "工程路由区块.md"
    return SKILL_ROOT / "assets" / "en" / "engineering-router.md"


def render_router(
    invariant_map, language: str, *, asset_data: bytes | None = None
) -> str:
    asset_path = router_asset_path(language)
    if asset_path.is_symlink() or not asset_path.is_file():
        raise InvariantContractError(f"router asset is missing: {asset_path}")
    try:
        if asset_data is None:
            with asset_path.open("r", encoding="utf-8", newline="") as handle:
                asset = handle.read()
        else:
            asset = asset_data.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise InvariantContractError("router asset is not readable UTF-8") from error
    if (
        "\r" in asset
        or not asset.endswith("\n")
        or asset.endswith("\n\n")
        or asset.count("{{ROUTER_ROWS}}") != 1
    ):
        raise InvariantContractError("router asset has an invalid format")
    rendered_rows = router_rows(invariant_map, language=language)
    if not rendered_rows:
        rendered_rows = ("| — | — | — | — |",)
    rendered = asset.replace("{{ROUTER_ROWS}}", "\n".join(rendered_rows))
    try:
        span = locate_managed_block(
            rendered,
            ROUTER_START_MARKER,
            ROUTER_END_MARKER,
            "engineering router asset",
        )
    except ManagedBlockError as error:
        raise InvariantContractError(str(error)) from error
    if span is None or span.start != 0 or span.end != len(rendered):
        raise InvariantContractError("router asset markers must wrap the whole asset")
    return rendered


def update_router(text: str, rendered: str) -> tuple[str, str]:
    try:
        span = locate_managed_block(
            text,
            ROUTER_START_MARKER,
            ROUTER_END_MARKER,
            "root AGENTS.md engineering router",
        )
        navigation_span = locate_managed_block(
            text,
            DOCUMENT_NAV_START_MARKER,
            DOCUMENT_NAV_END_MARKER,
            "root AGENTS.md document navigation",
        )
    except ManagedBlockError as error:
        raise InvariantContractError(str(error)) from error
    if span is not None and navigation_span is not None:
        separated = (
            span.end <= navigation_span.start
            or navigation_span.end <= span.start
        )
        if not separated:
            raise InvariantContractError(
                "root AGENTS.md engineering router and document navigation "
                "must not overlap"
            )
    try:
        locate_all_managed_blocks(text)
    except ManagedBlockError as error:
        raise InvariantContractError(str(error)) from error
    if span is not None:
        outside = text[: span.start] + text[span.end :]
        if visible_section_titles(outside, ROUTER_TITLES):
            raise InvariantContractError(
                "root AGENTS.md has a duplicate unowned engineering-router heading"
            )
        candidate = text[: span.start] + rendered + text[span.end :]
        action = "updated"
    else:
        existing_titles = visible_section_titles(text, ROUTER_TITLES)
        if existing_titles:
            raise InvariantContractError(
                "root AGENTS.md has an unowned or drifted engineering-router heading"
            )
        newline = "\r\n" if "\r\n" in text else "\n"
        prefix = text
        if prefix and not prefix.endswith(newline):
            prefix += newline
        if prefix and not prefix.endswith(newline * 2):
            prefix += newline
        candidate = prefix + rendered
        action = "inserted"

    try:
        locate_all_managed_blocks(candidate)
        candidate_span = locate_managed_block(
            candidate,
            ROUTER_START_MARKER,
            ROUTER_END_MARKER,
            "projected root AGENTS.md engineering router",
        )
    except ManagedBlockError as error:
        raise InvariantContractError(str(error)) from error
    if candidate_span is None:
        raise InvariantContractError(
            "projected engineering-router markers are hidden by Markdown structure"
        )
    return candidate, action


def router_source_paths(root: Path, invariant_map, profiles_root: str | None) -> tuple[Path, ...]:
    """Return every regular file consumed by map and reference validation."""

    paths: set[Path] = set()
    for binding in invariant_map.bindings:
        paths.add(root / binding.authority.path)
        for reference in binding.evidence + binding.enforcement.evidence:
            paths.add(root / reference.split("#", 1)[0])
    if invariant_map.profile_selection is not None:
        paths.add(root / invariant_map.profile_selection.path)

    needs_profiles = invariant_map.profile_selection is not None or any(
        isinstance(binding.source, ProfileSource)
        for binding in invariant_map.bindings
    )
    if needs_profiles:
        import architecture_profiles

        package_root = (
            Path(profiles_root)
            if profiles_root is not None
            else architecture_profiles.default_profiles_root()
        )
        package = architecture_profiles.load_package(package_root)
        paths.add(package_root / "catalog.json")
        for entry in package.catalog["profiles"]:
            paths.add(
                architecture_profiles.safe_child(
                    package_root,
                    entry["path"],
                    "catalog profile path",
                )
            )
    return tuple(sorted(paths, key=lambda path: str(path.absolute())))


def snapshot_paths(paths: tuple[Path, ...]):
    """Take one stable snapshot per absolute path, preserving a deterministic order."""

    unique = {path.absolute(): path for path in paths}
    return tuple(
        (unique[key], read_snapshot(unique[key]))
        for key in sorted(unique, key=str)
    )


def path_identities(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(sorted((path.absolute() for path in paths), key=str))


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    if not root.is_dir():
        print(f"error: project root is not a directory: {root}")
        return 2
    agents_path = root / "AGENTS.md"
    map_path = find_invariant_map(root)

    if map_path is None:
        agents_snapshot = None
        if agents_path.is_file() and not agents_path.is_symlink():
            try:
                agents_snapshot = read_snapshot(agents_path)
                text = agents_snapshot.data.decode("utf-8")
                span = locate_managed_block(
                    text,
                    ROUTER_START_MARKER,
                    ROUTER_END_MARKER,
                    "root AGENTS.md engineering router",
                )
            except (OSError, UnicodeError, ManagedBlockError, ValueError) as error:
                print(f"error: {error}")
                return 1
            if span is not None:
                print(
                    f"error: engineering router exists without {INVARIANT_MAP_RELATIVE_PATH}"
                )
                return 1
        if find_invariant_map(root) is not None:
            print(
                "error: invariant map appeared during validation; AGENTS.md unchanged"
            )
            return 1
        if agents_snapshot is not None:
            try:
                if read_snapshot(agents_path) != agents_snapshot:
                    raise ValueError("AGENTS.md changed during validation")
            except ValueError as error:
                print(f"error: {error}; AGENTS.md unchanged")
                return 1
        print("invariant map absent; engineering router unchanged")
        return 0

    if agents_path.is_symlink() or not agents_path.is_file():
        print("error: invariant map requires an existing regular root AGENTS.md")
        return 1
    profiles_root = args.profiles_root
    try:
        agents_snapshot = read_snapshot(agents_path)
        map_snapshot = read_snapshot(map_path)
        original = agents_snapshot.data.decode("utf-8")
        preliminary_map = load_invariant_map(map_path, profiles_root)
        source_paths = router_source_paths(root, preliminary_map, profiles_root)
        source_snapshots = snapshot_paths(source_paths)
        invariant_map = load_invariant_map(map_path, profiles_root)
        if path_identities(
            router_source_paths(root, invariant_map, profiles_root)
        ) != path_identities(source_paths):
            raise InvariantContractError(
                "invariant validation source paths changed during validation"
            )
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
        canonical_snapshots = tuple(
            (root / relative, read_snapshot(root / relative))
            for relative in sorted(allowed)
        )
        reference_errors = validate_project_references(
            root, invariant_map, allowed_authorities=allowed
        )
        if reference_errors:
            raise InvariantContractError("; ".join(reference_errors))
        language = detect_language(root, args.language)
        asset_path = router_asset_path(language)
        asset_snapshot = read_snapshot(asset_path)
        rendered = render_router(
            invariant_map, language, asset_data=asset_snapshot.data
        )
        updated, action = update_router(original, rendered)
        if read_snapshot(map_path) != map_snapshot:
            raise InvariantContractError("invariant map changed during validation")
        for path, snapshot in source_snapshots:
            if read_snapshot(path) != snapshot:
                raise InvariantContractError(
                    f"{path.name} changed during invariant validation"
                )
        for path, snapshot in canonical_snapshots:
            if read_snapshot(path) != snapshot:
                raise InvariantContractError(
                    f"{path.name} changed during router validation"
                )
    except (OSError, UnicodeError, InvariantContractError) as error:
        print(f"error: {error}; AGENTS.md unchanged")
        return 1
    except ValueError as error:
        print(f"error: {error}; AGENTS.md unchanged")
        return 1

    input_snapshots = (
        (map_path, map_snapshot),
        (asset_path, asset_snapshot),
        *source_snapshots,
        *canonical_snapshots,
    )

    def precommit_validate() -> None:
        current_map_path = find_invariant_map(root)
        if current_map_path is None or current_map_path.resolve() != map_path.resolve():
            raise InvariantContractError("invariant map path changed before write")
        if read_snapshot(map_path) != map_snapshot:
            raise InvariantContractError("invariant map changed before write")
        current_map = load_invariant_map(map_path, profiles_root)
        current_source_paths = router_source_paths(
            root, current_map, profiles_root
        )
        if path_identities(current_source_paths) != path_identities(source_paths):
            raise InvariantContractError(
                "invariant validation source paths changed before write"
            )
        for path, snapshot in source_snapshots:
            if read_snapshot(path) != snapshot:
                raise InvariantContractError(
                    f"{path.name} changed before router write"
                )
        current_context = resolve_project_docs(root)
        if (
            current_context.errors
            or current_context.language is not context.language
            or current_context.selected != context.selected
        ):
            raise InvariantContractError(
                "canonical document paths or language changed before write"
            )
        current_allowed = {
            "STATUS.md",
            "CONTRIBUTING.md",
            current_context.selected["product"],
            current_context.selected["architecture"],
            current_context.selected["development_rules"],
            current_context.selected["source_size_rules"],
        }
        current_errors = validate_project_references(
            root, current_map, allowed_authorities=current_allowed
        )
        if current_errors:
            raise InvariantContractError("; ".join(current_errors))
        current_language = detect_language(root, args.language)
        if current_language != language:
            raise InvariantContractError("router language changed before write")
        if router_asset_path(current_language) != asset_path:
            raise InvariantContractError("router asset path changed before write")
        current_asset = read_snapshot(asset_path)
        if current_asset != asset_snapshot:
            raise InvariantContractError("router asset changed before write")
        current_rendered = render_router(
            current_map,
            current_language,
            asset_data=current_asset.data,
        )
        current_updated, current_action = update_router(original, current_rendered)
        if (
            current_rendered != rendered
            or current_updated != updated
            or current_action != action
        ):
            raise InvariantContractError("engineering router projection changed")

    if updated == original:
        try:
            precommit_validate()
            if read_snapshot(agents_path) != agents_snapshot:
                raise ValueError("AGENTS.md changed during validation")
            for path, snapshot in input_snapshots:
                if read_snapshot(path) != snapshot:
                    raise ValueError(f"{path.name} changed during validation")
        except (OSError, UnicodeError, InvariantContractError, ValueError) as error:
            print(f"error: {error}; AGENTS.md unchanged")
            return 1
        print("engineering router already matches invariant map; unchanged")
        return 0

    try:
        write_atomically(
            agents_path,
            updated,
            agents_snapshot,
            precommit_validate,
            input_snapshots=input_snapshots,
        )
    except AtomicWriteCommittedError as error:
        print(f"error: {error}; AGENTS.md was replaced")
        return 1
    except (OSError, UnicodeError, InvariantContractError, ValueError) as error:
        print(f"error: {error}; AGENTS.md unchanged")
        return 1
    print(f"{action} root AGENTS.md engineering router")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
