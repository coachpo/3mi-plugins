"""Adapter v2 validation, safe project paths, and reproducible source identity."""

from __future__ import annotations

import importlib.util
import math
import os
import re
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from model import (
    ADAPTER_SCHEMA_VERSION,
    SUPPORTED_PROVIDERS,
    AdapterError,
    CampaignError,
    assert_persistable,
    canonical_bytes,
    has_secret_like,
    read_json,
    read_regular_bytes,
    sha256_bytes,
)

MAX_SOURCE_ENTRIES = 500_000
MAX_SOURCE_FILE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
CRITERION_ID_PATTERN = re.compile(r"^C[1-9][0-9]*$")
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SUPPORTED_PLATFORMS = {"any", "darwin", "windows", "linux", "posix"}
GIT_ENVIRONMENT_KEYS = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES", "GIT_COMMON_DIR",
    "GIT_DIR", "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_WORK_TREE",
}
PLUGIN_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def _load_goal_contract_module():
    path = PLUGIN_SCRIPTS / "goal_contract.py"
    specification = importlib.util.spec_from_file_location("steward_goal_contract", path)
    if specification is None or specification.loader is None:
        raise AdapterError("cannot load the Steward GOAL contract validator")
    module = importlib.util.module_from_spec(specification)
    try:
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
    except Exception as exc:
        raise AdapterError("cannot load the Steward GOAL contract validator") from exc
    return module


def _load_worktree_binding_module():
    path = PLUGIN_SCRIPTS / "worktree_binding.py"
    specification = importlib.util.spec_from_file_location(
        "steward_worktree_binding", path
    )
    if specification is None or specification.loader is None:
        raise AdapterError("cannot load the Steward worktree binding validator")
    module = importlib.util.module_from_spec(specification)
    try:
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
    except Exception as exc:
        raise AdapterError("cannot load the Steward worktree binding validator") from exc
    return module


def _load_goal_workspace_module():
    path = PLUGIN_SCRIPTS / "goal_workspace.py"
    specification = importlib.util.spec_from_file_location(
        "steward_goal_workspace", path
    )
    if specification is None or specification.loader is None:
        raise AdapterError("cannot load the Steward GOAL workspace validator")
    module = importlib.util.module_from_spec(specification)
    try:
        scripts_value = str(PLUGIN_SCRIPTS)
        if scripts_value not in sys.path:
            sys.path.insert(0, scripts_value)
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
    except Exception as exc:
        raise AdapterError("cannot load the Steward GOAL workspace validator") from exc
    return module


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def path_has_traversal(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return "\x00" in value or any(part == ".." for part in normalized.split("/"))


def normalize_relative(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise AdapterError(label + " must be a non-empty relative path")
    normalized = value.replace("\\", "/")
    if normalized == ".":
        return "."
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or re.match(r"^[A-Za-z]:", normalized):
        raise AdapterError(label + " must be relative")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise AdapterError(label + " is not normalized")
    return "/".join(parts)


def path_has_symlink_component(path: Path) -> bool:
    try:
        absolute = path.absolute()
    except (OSError, ValueError):
        return True
    for candidate in (absolute, *absolute.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            return True
    return False


def path_uses_symlink(path: Path, root: Path) -> bool:
    try:
        root_absolute = root.absolute()
        candidate = path.absolute()
        relative = candidate.relative_to(root_absolute)
    except (OSError, ValueError):
        return True
    current = root_absolute
    try:
        root_metadata = current.lstat()
        if stat.S_ISLNK(root_metadata.st_mode) or _is_reparse(root_metadata):
            return True
    except OSError:
        return True
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            return True
    return False


def resolve_project_path(root: Path, value: str, label: str) -> Path:
    relative = normalize_relative(value, label)
    unresolved = root if relative == "." else root / relative
    if path_uses_symlink(unresolved, root):
        raise AdapterError(label + " uses a symlink/reparse path")
    root_real = Path(os.path.realpath(str(root)))
    candidate = Path(os.path.realpath(str(unresolved)))
    if not is_within(candidate, root_real):
        raise AdapterError(label + " escapes projectRoot")
    return candidate


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise CampaignError("path escapes its declared root") from exc


def covers_exclude(exclude: str, relative: str) -> bool:
    base = exclude.removesuffix("/**")
    return relative == base or relative.startswith(base + "/")


def current_platform() -> str:
    if os.name == "nt":
        return "windows"
    if __import__("sys").platform == "darwin":
        return "darwin"
    if __import__("sys").platform.startswith("linux"):
        return "linux"
    return "posix" if os.name == "posix" else "unknown"


def platform_supported_on(value: str, pinned_runtime: str) -> bool:
    if value == "any":
        return True
    if value == "posix":
        return pinned_runtime in {"darwin", "linux", "posix"}
    return value == pinned_runtime


def platform_supported(value: str) -> bool:
    return platform_supported_on(value, current_platform())


def _reject_nul(value: Any, label: str = "adapter") -> None:
    if isinstance(value, str) and "\x00" in value:
        raise AdapterError(label + " contains a NUL character")
    if isinstance(value, list):
        for item in value:
            _reject_nul(item, label)
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_nul(key, label)
            _reject_nul(item, label)


def _unique_strings(value: Any, label: str, pattern: re.Pattern[str] | None = None) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AdapterError(label + " must be a string array")
    if len(value) != len(set(value)):
        raise AdapterError(label + " contains duplicate values")
    if pattern is not None and any(pattern.fullmatch(item) is None for item in value):
        raise AdapterError(label + " contains an invalid identifier")
    return list(value)


def validate_evidence_contract(case_id: str, value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise AdapterError("case " + case_id + " evidence must be an object")
    if set(value) != {"requiredFiles", "nonEmptyFiles"}:
        raise AdapterError("case " + case_id + " evidence has invalid fields")
    required = _unique_strings(value["requiredFiles"], "case " + case_id + " evidence.requiredFiles")
    non_empty = _unique_strings(value["nonEmptyFiles"], "case " + case_id + " evidence.nonEmptyFiles")
    required_normalized = [normalize_relative(item, "case " + case_id + " evidence file") for item in required]
    non_empty_normalized = [normalize_relative(item, "case " + case_id + " non-empty evidence file") for item in non_empty]
    if any(item == "." for item in required_normalized + non_empty_normalized):
        raise AdapterError("case " + case_id + " evidence cannot name its directory")
    if not set(non_empty_normalized).issubset(required_normalized):
        raise AdapterError("case " + case_id + " nonEmptyFiles must be requiredFiles")
    return {
        "requiredFiles": required_normalized,
        "nonEmptyFiles": non_empty_normalized,
    }


class Adapter:
    def __init__(
        self,
        path: Path,
        data: dict[str, Any],
        project_root: Path,
        campaign_root: Path,
        excludes: list[str],
        catalog_fingerprint: str,
        goal_snapshot: dict[str, Any],
        goal_errors: list[str],
        worktree_binding: dict[str, Any],
        goal_workspace_errors: list[str],
    ) -> None:
        self.path = path
        self.data = data
        self.project_root = project_root
        self.campaign_root = campaign_root
        self.excludes = excludes
        self.catalog_fingerprint = catalog_fingerprint
        self.goal_snapshot = goal_snapshot
        self.goal_errors = goal_errors
        self.worktree_binding = worktree_binding
        self.goal_workspace_errors = goal_workspace_errors
        self.goal_criteria_ids = set(goal_snapshot["criteriaIds"])
        self.cases: list[dict[str, Any]] = data["cases"]
        self.case_by_id = {case["id"]: case for case in self.cases}

    def case_metadata(self) -> list[dict[str, Any]]:
        return [
            {
                "id": case["id"],
                "required": case["required"],
                "platform": case["platform"],
                "dependsOn": list(case["dependsOn"]),
                "coversCriteria": list(case["coversCriteria"]),
                "evidence": {
                    "requiredFiles": list(case["evidence"]["requiredFiles"]),
                    "nonEmptyFiles": list(case["evidence"]["nonEmptyFiles"]),
                },
            }
            for case in self.cases
        ]

    def criteria_configuration(self) -> list[dict[str, Any]]:
        return [
            {
                "id": criterion,
                "requiredCaseIds": [
                    case["id"] for case in self.cases
                    if case["required"] and criterion in case["coversCriteria"]
                ],
            }
            for criterion in sorted(self.goal_criteria_ids, key=lambda item: int(item[1:]))
        ]


def _goal_snapshot(project_root: Path, contract: dict[str, Any], observe_drift: bool) -> tuple[dict[str, Any], list[str]]:
    expected_keys = {"path", "contractVersion", "sha256"}
    if not isinstance(contract, dict) or set(contract) != expected_keys:
        raise AdapterError("goalContract has invalid fields")
    if contract.get("path") != ".steward/goal.txt":
        raise AdapterError("goalContract.path must be .steward/goal.txt")
    if type(contract.get("contractVersion")) is not int or contract["contractVersion"] != 1:
        raise AdapterError("goalContract.contractVersion must be 1")
    if not isinstance(contract.get("sha256"), str) or HASH_PATTERN.fullmatch(contract["sha256"]) is None:
        raise AdapterError("goalContract.sha256 must be a lowercase sha256 digest")
    goal_path = resolve_project_path(project_root, contract["path"], "goalContract.path")
    module = _load_goal_contract_module()
    try:
        parsed = module.load_goal_contract(goal_path)
        actual_digest = module.goal_contract_sha256(parsed)
        view = module.goal_contract_view(parsed)
    except Exception as exc:
        if not observe_drift:
            raise AdapterError("GOAL_CONTRACT_DRIFT: cannot validate .steward/goal.txt") from exc
        return {
            "path": contract["path"],
            "contractVersion": 1,
            "sha256": contract["sha256"],
            "criteriaIds": [],
        }, ["GOAL_CONTRACT_DRIFT"]
    snapshot = {
        "path": contract["path"],
        "contractVersion": 1,
        "sha256": contract["sha256"],
        "criteriaIds": [item["id"] for item in view["completionCriteria"]],
    }
    errors = [] if actual_digest == contract["sha256"] else ["GOAL_CONTRACT_DRIFT"]
    if errors and not observe_drift:
        raise AdapterError(errors[0] + ": goalContract digest does not match .steward/goal.txt")
    return snapshot, errors


def validate_adapter(adapter_path: Path, *, observe_goal_drift: bool = False, **_ignored: Any) -> Adapter:
    """Validate the exact greenfield adapter v2 contract."""

    if "\x00" in str(adapter_path):
        raise AdapterError("adapter path contains a NUL character")
    supplied = adapter_path.absolute()
    if path_has_symlink_component(supplied):
        raise AdapterError("adapter file uses a symlink/reparse path")
    adapter_path = Path(os.path.realpath(str(supplied)))
    if not adapter_path.is_file():
        raise AdapterError("adapter file does not exist: " + str(adapter_path))
    data = read_json(adapter_path)
    if not isinstance(data, dict):
        raise AdapterError("adapter root must be a JSON object")
    _reject_nul(data)
    expected_top = {
        "schemaVersion", "projectId", "projectRoot", "campaignRoot", "source",
        "localOnly", "goalContract", "cases",
    }
    if set(data) != expected_top:
        raise AdapterError("adapter has invalid fields")
    if type(data.get("schemaVersion")) is not int or data["schemaVersion"] != ADAPTER_SCHEMA_VERSION:
        raise AdapterError("adapter schemaVersion must be 2")
    if not isinstance(data["projectId"], str) or not data["projectId"].strip():
        raise AdapterError("projectId must be a non-empty string")
    if data["projectRoot"] != "..":
        raise AdapterError("projectRoot must be ..")
    if data["campaignRoot"] != ".steward/verification/campaign":
        raise AdapterError("campaignRoot must be .steward/verification/campaign")
    project_root = Path(os.path.realpath(str(adapter_path.parent / "..")))
    if path_has_symlink_component(project_root) or not project_root.is_dir():
        raise AdapterError("projectRoot must be an existing non-link directory")
    binding_module = _load_worktree_binding_module()
    try:
        worktree_binding = binding_module.bind_target_worktree(str(project_root)).view()
    except Exception as exc:
        raise AdapterError("cannot bind projectRoot as the exact target worktree") from exc
    expected_adapter = project_root / ".steward" / "project-adapter.json"
    if adapter_path != expected_adapter:
        raise AdapterError("adapter path must be .steward/project-adapter.json")
    campaign_root = resolve_project_path(project_root, data["campaignRoot"], "campaignRoot")

    source = data["source"]
    if not isinstance(source, dict):
        raise AdapterError("source must be an object")
    provider = source.get("provider")
    allowed_source = {"provider", "excludes"}
    if provider == "manifest":
        allowed_source.add("manifest")
    elif provider == "files":
        allowed_source.add("files")
    if provider not in SUPPORTED_PROVIDERS or set(source) != allowed_source:
        raise AdapterError("source has invalid fields for its provider")
    excludes = _unique_strings(source["excludes"], "source.excludes")
    excludes = [normalize_relative(item, "source exclude") for item in excludes]
    if ".steward" not in excludes:
        raise AdapterError("source.excludes must contain .steward")

    local_only = data["localOnly"]
    if not isinstance(local_only, dict) or set(local_only) != {"enabled", "allowedExternalCapabilities"}:
        raise AdapterError("localOnly has invalid fields")
    if local_only["enabled"] is not True:
        raise AdapterError("localOnly.enabled must be true")
    allowed_capabilities = _unique_strings(
        local_only["allowedExternalCapabilities"], "localOnly.allowedExternalCapabilities"
    )
    if any(not item for item in allowed_capabilities):
        raise AdapterError("external capability names must be non-empty")

    goal_snapshot, goal_errors = _goal_snapshot(
        project_root, data["goalContract"], observe_goal_drift
    )
    goal_workspace_errors: list[str] = []
    try:
        workspace_view = _load_goal_workspace_module().view_goal_workspace(
            str(project_root)
        )
        workspace_contract = workspace_view.get("goalContract", {})
        if (
            workspace_view.get("schemaId") != "steward.goal-workspace"
            or workspace_view.get("schemaVersion") != 1
            or workspace_contract.get("path") != goal_snapshot["path"]
            or workspace_contract.get("contractVersion")
            != goal_snapshot["contractVersion"]
            or workspace_contract.get("sha256") != goal_snapshot["sha256"]
            or workspace_contract.get("criteriaIds")
            != goal_snapshot["criteriaIds"]
        ):
            raise AdapterError("GOAL workspace view does not match goalContract")
    except Exception as exc:
        goal_workspace_errors = ["GOAL_WORKSPACE_INVALID"]
        if not observe_goal_drift:
            raise AdapterError(
                "GOAL_WORKSPACE_INVALID: cannot validate the Steward GOAL workspace"
            ) from exc
    criteria_ids = set(goal_snapshot["criteriaIds"])

    cases = data["cases"]
    if not isinstance(cases, list) or not cases:
        raise AdapterError("cases must be a non-empty array")
    expected_case = {
        "id", "required", "platform", "dependsOn", "coversCriteria", "argv",
        "cwd", "timeoutSeconds", "fixture", "externalCapabilities", "evidence",
    }
    ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or set(case) != expected_case:
            raise AdapterError("case " + str(index) + " has invalid fields")
        case_id = case["id"]
        if not isinstance(case_id, str) or CASE_ID_PATTERN.fullmatch(case_id) is None:
            raise AdapterError("case IDs must use letters, digits, dot, underscore, or hyphen")
        if case_id in ids:
            raise AdapterError("duplicate case id: " + case_id)
        ids.add(case_id)
        if type(case["required"]) is not bool:
            raise AdapterError("case " + case_id + " required must be a boolean")
        if case["platform"] not in SUPPORTED_PLATFORMS:
            raise AdapterError("case " + case_id + " platform is unsupported")
        case["dependsOn"] = _unique_strings(case["dependsOn"], "case " + case_id + " dependsOn", CASE_ID_PATTERN)
        case["coversCriteria"] = _unique_strings(
            case["coversCriteria"], "case " + case_id + " coversCriteria", CRITERION_ID_PATTERN
        )
        if not goal_errors and not set(case["coversCriteria"]).issubset(criteria_ids):
            raise AdapterError("case " + case_id + " references an unknown GOAL criterion")
        argv = case["argv"]
        if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
            raise AdapterError("case " + case_id + " argv must be a non-empty string array")
        if any(has_secret_like(item) for item in argv):
            raise AdapterError("case " + case_id + " contains secret-like argv")
        secret_option = re.compile(
            r"^--?(?:api[-_]?key|access[-_]?token|auth[-_]?token|token|password|passwd|secret|credential|private[-_]?key)$",
            re.IGNORECASE,
        )
        if any(secret_option.match(argv[position]) for position in range(len(argv) - 1)):
            raise AdapterError("case " + case_id + " contains a secret-bearing argv option")
        timeout = case["timeoutSeconds"]
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0 or timeout > 7 * 24 * 60 * 60:
            raise AdapterError("case " + case_id + " timeoutSeconds is invalid")
        if not isinstance(case["cwd"], str):
            raise AdapterError("case " + case_id + " cwd must be a path string")
        cwd = resolve_project_path(project_root, case["cwd"], "case " + case_id + " cwd")
        if not cwd.is_dir():
            raise AdapterError("case " + case_id + " cwd must be an existing directory")
        fixture = case["fixture"]
        if isinstance(fixture, str):
            fixture_path = resolve_project_path(project_root, fixture, "case " + case_id + " fixture")
            if not fixture_path.exists():
                raise AdapterError("case " + case_id + " fixture path does not exist")
        elif fixture is not None and not isinstance(fixture, dict):
            raise AdapterError("case " + case_id + " fixture must be null, a path, or an object")
        capabilities = _unique_strings(case["externalCapabilities"], "case " + case_id + " externalCapabilities")
        if not set(capabilities).issubset(allowed_capabilities):
            raise AdapterError("case " + case_id + " requests a disallowed external capability")
        case["evidence"] = validate_evidence_contract(case_id, case["evidence"])

    positions = {case["id"]: index for index, case in enumerate(cases)}
    for case in cases:
        for dependency in case["dependsOn"]:
            if dependency not in positions:
                raise AdapterError("case " + case["id"] + " depends on an unknown case")
            if positions[dependency] >= positions[case["id"]]:
                raise AdapterError("case dependencies must point to an earlier case")
    if not goal_errors:
        uncovered = [
            criterion for criterion in criteria_ids
            if not any(case["required"] and criterion in case["coversCriteria"] for case in cases)
        ]
        if uncovered:
            raise AdapterError("GOAL criteria require required-case coverage: " + ", ".join(sorted(uncovered)))

    if provider == "manifest":
        manifest = source.get("manifest")
        if not isinstance(manifest, str):
            raise AdapterError("source.manifest must be a path string")
        manifest_path = resolve_project_path(project_root, manifest, "source.manifest")
        if not manifest_path.is_file():
            raise AdapterError("source.manifest must be an existing file")
    elif provider == "files":
        files = _unique_strings(source.get("files"), "source.files")
        if not files:
            raise AdapterError("source.files must not be empty")
        for item in files:
            normalize_relative(item, "source file")

    assert_persistable(data)
    adapter = Adapter(
        adapter_path, data, project_root, campaign_root, excludes,
        sha256_bytes(canonical_bytes(data)), goal_snapshot, goal_errors,
        worktree_binding, goal_workspace_errors,
    )
    try:
        observe_source(adapter)
    except CampaignError as exc:
        raise AdapterError(str(exc)) from exc
    return adapter


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in GIT_ENVIRONMENT_KEYS:
        environment.pop(name, None)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def _git_source_paths(adapter: Adapter) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(adapter.project_root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            check=False, capture_output=True,
            env=_git_environment(), timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CampaignError("cannot enumerate Git source") from exc
    if completed.returncode != 0:
        raise CampaignError("cannot enumerate Git source")
    try:
        decoded = completed.stdout.decode("utf-8")
    except UnicodeError as exc:
        raise CampaignError("Git source paths are not valid UTF-8") from exc
    return [item for item in decoded.split("\x00") if item]


def _manifest_source_paths(adapter: Adapter) -> list[str]:
    manifest_relative = normalize_relative(adapter.data["source"]["manifest"], "source.manifest")
    value = read_json(adapter.project_root / manifest_relative)
    if isinstance(value, dict) and set(value) == {"files"}:
        value = value["files"]
    paths = _unique_strings(value, "source manifest files")
    if not paths:
        raise CampaignError("source manifest must declare project source files")
    return [manifest_relative, *paths]


def _declared_source_paths(adapter: Adapter) -> list[str]:
    provider = adapter.data["source"]["provider"]
    if provider == "git":
        raw = _git_source_paths(adapter)
    elif provider == "manifest":
        raw = _manifest_source_paths(adapter)
    else:
        raw = adapter.data["source"]["files"]
    normalized: list[str] = []
    for item in raw:
        relative = normalize_relative(item, "source file")
        if relative == ".":
            raise CampaignError("source inventory cannot contain projectRoot")
        if any(covers_exclude(exclude, relative) for exclude in adapter.excludes):
            continue
        normalized.append(relative)
    result = sorted(set(normalized))
    if len(result) > MAX_SOURCE_ENTRIES:
        raise CampaignError("source inventory exceeds the safe entry limit")
    return result


def _source_entry(adapter: Adapter, relative: str) -> dict[str, Any]:
    unresolved = adapter.project_root / relative
    if path_uses_symlink(unresolved, adapter.project_root):
        raise CampaignError("source path uses a symlink/reparse point: " + relative)
    try:
        metadata = unresolved.lstat()
    except FileNotFoundError:
        return {"path": relative, "status": "missing"}
    except OSError as exc:
        raise CampaignError("cannot inspect source path: " + relative) from exc
    if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise CampaignError("source path is not a regular non-link file: " + relative)
    content = read_regular_bytes(unresolved, label="source file", max_bytes=MAX_SOURCE_FILE_BYTES)
    try:
        after = unresolved.lstat()
    except OSError as exc:
        raise CampaignError("source path changed while it was observed: " + relative) from exc
    if (
        not os.path.samestat(metadata, after)
        or metadata.st_mode != after.st_mode
        or metadata.st_size != after.st_size
        or getattr(metadata, "st_mtime_ns", None)
        != getattr(after, "st_mtime_ns", None)
        or getattr(metadata, "st_ctime_ns", None)
        != getattr(after, "st_ctime_ns", None)
        or path_uses_symlink(unresolved, adapter.project_root)
    ):
        raise CampaignError("source path changed while it was observed: " + relative)
    entry = {
        "path": relative,
        "status": "present",
        "size": len(content),
        "sha256": sha256_bytes(content),
        "executable": bool(metadata.st_mode & 0o111),
    }
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        entry["lineCount"] = len(text.splitlines())
    return entry


def observe_source(adapter: Adapter) -> dict[str, Any]:
    entries = [_source_entry(adapter, relative) for relative in _declared_source_paths(adapter)]
    control_paths: set[str] = set()
    if adapter.data["source"]["provider"] == "manifest":
        control_paths.add(
            normalize_relative(adapter.data["source"]["manifest"], "source.manifest")
        )
    if not any(
        item.get("status") == "present" and item["path"] not in control_paths
        for item in entries
    ):
        raise CampaignError(
            "source inventory must contain a present non-control project source file"
        )
    total = sum(item.get("size", 0) for item in entries)
    if total > MAX_SOURCE_TOTAL_BYTES:
        raise CampaignError("source inventory exceeds the safe total size limit")
    identity = {
        "provider": adapter.data["source"]["provider"],
        "files": entries,
    }
    return {
        "fingerprint": sha256_bytes(canonical_bytes(identity)),
        "provider": identity["provider"],
        "files": entries,
        "projectPaths": [item["path"] for item in entries],
    }


def source_snapshot(adapter: Adapter) -> dict[str, Any]:
    return observe_source(adapter)


def source_snapshot_changed_entries(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, str]]:
    old = {item["path"]: item for item in before.get("files", [])}
    new = {item["path"]: item for item in after.get("files", [])}
    changes: list[dict[str, str]] = []
    for path in sorted(set(old) | set(new)):
        left = old.get(path, {"status": "missing"})
        right = new.get(path, {"status": "missing"})
        if left == right:
            continue
        if left.get("status") == "missing" and right.get("status") == "present":
            kind = "added"
        elif left.get("status") == "present" and right.get("status") == "missing":
            kind = "deleted"
        elif left.get("sha256") == right.get("sha256") and left.get("executable") != right.get("executable"):
            kind = "mode-only"
        else:
            kind = "modified"
        changes.append({"path": path, "change": kind})
    return changes


def source_snapshot_changed_paths(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return [item["path"] for item in source_snapshot_changed_entries(before, after)]


def source_file_entries(adapter: Adapter) -> list[str]:
    return _declared_source_paths(adapter)


def source_file_metadata(adapter: Adapter, relative: str) -> dict[str, Any]:
    normalized = normalize_relative(relative, "source path")
    observation = observe_source(adapter)
    for item in observation["files"]:
        if item["path"] == normalized:
            return item
    raise CampaignError("path is not in the project source inventory: " + normalized)


def fingerprint_source(adapter: Adapter) -> str:
    return observe_source(adapter)["fingerprint"]


def run_internal(argv: Sequence[str], cwd: Path, **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
    """Run a bounded internal helper without inheriting repository Git overrides."""
    try:
        return subprocess.run(
            list(argv), cwd=str(cwd), check=False, capture_output=True,
            timeout=120, env=_git_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CampaignError("internal command failed") from exc


__all__ = [
    "Adapter", "covers_exclude", "current_platform", "fingerprint_source",
    "is_within", "normalize_relative", "observe_source", "path_has_symlink_component",
    "path_has_traversal", "path_uses_symlink", "platform_supported",
    "platform_supported_on", "relative_to_root", "resolve_project_path",
    "run_internal", "source_file_entries", "source_file_metadata", "source_snapshot",
    "source_snapshot_changed_entries", "source_snapshot_changed_paths",
    "validate_adapter", "validate_evidence_contract",
]
