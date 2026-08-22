#!/usr/bin/env python3
"""Public CLI for provider-neutral project verification configuration.

This entry validates and renders configuration. Project case execution,
platform evidence export and aggregation, and completion audit remain owned by
the bundled run-closed-loop-verification kernel.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import stat
import sys
from pathlib import Path
from typing import Any, Sequence

# Public read-only modes must not create a local import cache when callers omit
# ``-B``.  The main script itself is never bytecode-cached.
sys.dont_write_bytecode = True

from verification_pipeline import (
    VerificationPipelineError,
    build_ci_plan,
    canonical_bytes,
    configure_project,
    load_ci_plan,
    load_impact_plan,
    load_profile,
    plan_impact,
    render_derived_adapter,
    render_github_actions,
    render_github_actions_bytes,
    render_local_entry,
    render_local_entry_bytes,
    review_configuration,
    write_json,
)


def _emit(value: Any) -> None:
    sys.stdout.buffer.write(canonical_bytes(value) + b"\n")


def _root(value: str | None) -> Path:
    return Path(value) if value is not None else Path.cwd()


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _translate_macos_system_alias(path: Path) -> Path:
    """Use the physical spelling of macOS' standard filesystem aliases."""

    if sys.platform != "darwin":
        return path
    for alias, target in (
        (Path("/var"), Path("/private/var")),
        (Path("/tmp"), Path("/private/tmp")),
        (Path("/etc"), Path("/private/etc")),
    ):
        try:
            return target / path.relative_to(alias)
        except ValueError:
            continue
    return path


def _checked_lexical_absolute(value: str | Path, label: str) -> Path:
    """Inspect the raw path walk before normalization can hide a link hop."""

    supplied = Path(value)
    if not supplied.is_absolute():
        supplied = Path.cwd() / supplied
    supplied = _translate_macos_system_alias(supplied)
    current = Path(supplied.anchor)
    parts = supplied.parts[1:] if supplied.anchor else supplied.parts
    for index, part in enumerate(parts):
        if part in {"", "."}:
            continue
        if part == "..":
            current = current.parent
            continue
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise VerificationPipelineError(label + " cannot be inspected") from exc
        if _is_link_or_reparse(metadata):
            raise VerificationPipelineError(label + " uses a symlink/reparse path")
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise VerificationPipelineError(
                label + " uses a non-directory path component"
            )
    return current


def _inside(
    root: Path,
    value: str | Path,
    label: str,
    *,
    allow_directory: bool = False,
) -> Path:
    absolute_root = _checked_lexical_absolute(root, "projectRoot")
    try:
        root_metadata = absolute_root.lstat()
    except OSError as exc:
        raise VerificationPipelineError("projectRoot cannot be inspected") from exc
    if _is_link_or_reparse(root_metadata) or not stat.S_ISDIR(root_metadata.st_mode):
        raise VerificationPipelineError(
            "projectRoot must be a regular non-link directory"
        )
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = absolute_root / candidate
    try:
        lexical = _checked_lexical_absolute(candidate, label)
        relative = lexical.relative_to(absolute_root)
        current = absolute_root
        for part in relative.parts:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                continue
            if _is_link_or_reparse(metadata):
                raise VerificationPipelineError(
                    label + " uses a symlink/reparse path"
                )
            if current != lexical and not stat.S_ISDIR(metadata.st_mode):
                raise VerificationPipelineError(
                    label + " uses a non-directory path component"
                )
        resolved_root = absolute_root.resolve()
        resolved = candidate.resolve()
        resolved.relative_to(resolved_root)
        if resolved.exists():
            if allow_directory and not resolved.is_dir():
                raise VerificationPipelineError(label + " must name a directory")
            if not allow_directory and not resolved.is_file():
                raise VerificationPipelineError(label + " must name a file")
    except VerificationPipelineError:
        raise
    except (OSError, ValueError) as exc:
        raise VerificationPipelineError(label + " must be inside projectRoot") from exc
    return resolved


def _validate_static_io(
    profile: Any,
    *,
    outputs: Sequence[str],
    extra_sources: Sequence[tuple[str | Path, str]] = (),
) -> None:
    """Recheck all inputs and outputs immediately before a renderer call."""

    _inside(profile.project_root, profile.path, "verification profile")
    _inside(profile.project_root, profile.adapter_path, "adapter.path")
    plugin_root = profile.view["runtime"]["pluginRoot"]
    if plugin_root is not None:
        _inside(
            profile.project_root,
            plugin_root,
            "runtime.pluginRoot",
            allow_directory=True,
        )
    for value, label in extra_sources:
        _inside(profile.project_root, value, label)
    for key in outputs:
        _declared_output(profile, key)


def _declared_output(profile: Any, key: str) -> Path:
    return _inside(
        profile.project_root,
        profile.view["outputs"][key],
        "outputs." + key,
        allow_directory=key in {"derivedAdapters", "campaigns", "evidenceBundles"},
    )


def _require_exact_output(profile: Any, supplied: str, key: str) -> Path:
    output = _inside(profile.project_root, supplied, "output")
    if output != _declared_output(profile, key):
        raise VerificationPipelineError(
            "output must match profile outputs." + key
        )
    return output


def _require_under_output(profile: Any, supplied: str, key: str) -> Path:
    output = _inside(
        profile.project_root,
        supplied,
        "output",
        allow_directory=key == "campaigns",
    )
    base = _declared_output(profile, key)
    try:
        output.relative_to(base)
    except ValueError as exc:
        raise VerificationPipelineError(
            "output must be within profile outputs." + key
        ) from exc
    if output == base:
        raise VerificationPipelineError(
            "output must name a child of profile outputs." + key
        )
    return output


def _profile_input(args: argparse.Namespace) -> tuple[Path, Path]:
    root = _root(args.project_root)
    supplied = Path(args.profile)
    if not supplied.is_absolute():
        supplied = Path.cwd() / supplied
    return root, _inside(root, supplied, "verification profile")


def _profile(args: argparse.Namespace) -> Any:
    root, profile_path = _profile_input(args)
    profile = load_profile(profile_path, root)
    _inside(
        profile.project_root,
        profile.view["adapter"]["path"],
        "adapter.path",
    )
    plugin_root = profile.view["runtime"]["pluginRoot"]
    if plugin_root is not None:
        _inside(
            profile.project_root,
            plugin_root,
            "runtime.pluginRoot",
            allow_directory=True,
        )
    for key in profile.view["outputs"]:
        _declared_output(profile, key)
    return profile


def _byte_report(profile: Any, key: str, data: bytes, check: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "check": check,
        "output": profile.view["outputs"][key],
        "size": len(data),
        "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
    }


def _expected_report(profile: Any, key: str, data: bytes) -> dict[str, Any]:
    """Return exact candidate bytes without touching the declared output."""

    return {
        "ok": True,
        "mode": "expected",
        "writePerformed": False,
        "output": profile.view["outputs"][key],
        "size": len(data),
        "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        "contentEncoding": "base64",
        "contentBase64": base64.b64encode(data).decode("ascii"),
    }


def _handle(args: argparse.Namespace) -> Any:
    if args.command == "review":
        profile = _profile(args)
        return review_configuration(profile.path, profile.project_root)
    if args.command == "configure":
        profile = _profile(args)
        for value in args.allow_write:
            _inside(profile.project_root, value, "authorized write path")
        _validate_static_io(
            profile,
            outputs=("ciPlan", "localEntry", "workflow"),
        )
        return configure_project(
            profile.path,
            profile.project_root,
            args.allow_write,
        )

    profile = _profile(args)
    if args.command == "validate-profile":
        normalized = dict(profile.view)
        normalized.pop("adapterCatalogFingerprint", None)
        normalized.pop("adapterCaseIds", None)
        return {
            "ok": True,
            "schemaId": "steward.verification-profile-validation",
            "schemaVersion": 1,
            "profileFingerprint": profile.sha256,
            "verificationCatalogFingerprint": (
                profile.adapter_catalog_fingerprint
            ),
            "adapterCaseIds": list(profile.view["adapterCaseIds"]),
            "normalizedProfile": normalized,
        }
    if args.command == "plan-impact":
        plan = plan_impact(profile, profile.project_root, args.base_ref)
        output = _require_exact_output(profile, args.output, "impactPlan")
        write_json(output, plan)
        return plan
    if args.command == "validate-impact":
        path = _inside(profile.project_root, args.impact_plan, "impact plan")
        return load_impact_plan(path, profile, reobserve=True)
    if args.command == "build-ci-plan":
        plan = build_ci_plan(profile)
        if args.output is not None:
            raise VerificationPipelineError(
                "direct CI plan writes are disabled; use configure with the "
                "complete authorized write set"
            )
        return plan
    if args.command == "validate-ci-plan":
        path = _inside(profile.project_root, args.ci_plan, "CI plan")
        return load_ci_plan(path, profile)
    if args.command == "render-local":
        if not args.check and not args.expected:
            raise VerificationPipelineError(
                "direct renderer writes are disabled; use configure with the "
                "complete authorized write set"
            )
        _validate_static_io(profile, outputs=("localEntry",))
        if args.expected:
            return _expected_report(
                profile,
                "localEntry",
                render_local_entry_bytes(profile),
            )
        data = render_local_entry(profile, check=args.check)
        return _byte_report(profile, "localEntry", data, args.check)
    if args.command == "render-github":
        if not args.check and not args.expected:
            raise VerificationPipelineError(
                "direct renderer writes are disabled; use configure with the "
                "complete authorized write set"
            )
        if args.expected and args.ci_plan is None:
            _validate_static_io(profile, outputs=("workflow",))
            plan = build_ci_plan(profile)
        else:
            ci_path = _inside(
                profile.project_root,
                args.ci_plan or profile.view["outputs"]["ciPlan"],
                "CI plan",
            )
            _validate_static_io(
                profile,
                outputs=("workflow",),
                extra_sources=((ci_path, "CI plan"),),
            )
            plan = load_ci_plan(ci_path, profile)
        if args.expected:
            return _expected_report(
                profile,
                "workflow",
                render_github_actions_bytes(profile, plan),
            )
        data = render_github_actions(profile, plan, check=args.check)
        return _byte_report(profile, "workflow", data, args.check)
    if args.command == "render-adapter":
        output = _require_under_output(
            profile, args.output, "derivedAdapters"
        )
        campaign = _require_under_output(
            profile, args.campaign_root, "campaigns"
        )
        impact = None
        ci = None
        if args.impact_plan is not None:
            impact_path = _inside(
                profile.project_root, args.impact_plan, "impact plan"
            )
            impact = (
                impact_path,
                load_impact_plan(impact_path, profile, reobserve=True),
            )
        if args.ci_plan is not None:
            ci_path = _inside(profile.project_root, args.ci_plan, "CI plan")
            ci = (ci_path, load_ci_plan(ci_path, profile))
        value = render_derived_adapter(
            profile,
            tier=args.tier,
            output=output,
            campaign_root=campaign,
            impact_plan=impact,
            ci_plan=ci,
            entry_id=args.entry,
        )
        return value
    raise VerificationPipelineError("unsupported command")


def _add_profile(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True)
    parser.add_argument("--project-root")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure provider-neutral closed-loop verification"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_profile = subparsers.add_parser("validate-profile")
    _add_profile(validate_profile)

    impact = subparsers.add_parser("plan-impact")
    _add_profile(impact)
    impact.add_argument("--base-ref")
    impact.add_argument("--output", required=True)

    validate_impact = subparsers.add_parser("validate-impact")
    _add_profile(validate_impact)
    validate_impact.add_argument("--impact-plan", required=True)

    ci = subparsers.add_parser("build-ci-plan")
    _add_profile(ci)
    ci.add_argument(
        "--output",
        help="Legacy write option; rejected because configure owns static writes",
    )

    validate_ci = subparsers.add_parser("validate-ci-plan")
    _add_profile(validate_ci)
    validate_ci.add_argument("--ci-plan", required=True)

    adapter = subparsers.add_parser("render-adapter")
    _add_profile(adapter)
    adapter.add_argument("--tier", choices=("quick", "full"), required=True)
    plans = adapter.add_mutually_exclusive_group(required=True)
    plans.add_argument("--impact-plan")
    plans.add_argument("--ci-plan")
    adapter.add_argument("--entry")
    adapter.add_argument("--output", required=True)
    adapter.add_argument("--campaign-root", required=True)

    local = subparsers.add_parser("render-local")
    _add_profile(local)
    local_mode = local.add_mutually_exclusive_group()
    local_mode.add_argument("--check", action="store_true")
    local_mode.add_argument(
        "--expected",
        action="store_true",
        help="Report exact candidate bytes without writing the declared output",
    )

    github = subparsers.add_parser("render-github")
    _add_profile(github)
    github.add_argument("--ci-plan")
    github_mode = github.add_mutually_exclusive_group()
    github_mode.add_argument("--check", action="store_true")
    github_mode.add_argument(
        "--expected",
        action="store_true",
        help="Report exact candidate bytes without writing the declared output",
    )

    review = subparsers.add_parser("review")
    _add_profile(review)

    configure = subparsers.add_parser("configure")
    _add_profile(configure)
    configure.add_argument(
        "--allow-write",
        action="append",
        required=True,
        help="Project-relative path in the frozen authorized write set; repeat it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _handle(args)
    except VerificationPipelineError as exc:
        print("ERROR " + str(exc), file=sys.stderr)
        return 2
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
