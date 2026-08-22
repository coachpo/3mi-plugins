"""Public-CLI test helpers for the closed-loop verification kernel."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SKILL_ROOT = Path(__file__).resolve().parents[1]
KERNEL = SKILL_ROOT / "scripts" / "campaign.py"


def write_json(path: Path, value: Any) -> Path:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def json_output(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "CLI did not emit JSON\n"
            f"returncode={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        ) from exc
    if not isinstance(value, dict):
        raise AssertionError(f"CLI JSON output is not an object: {value!r}")
    return value


def run_cli(
    adapter: Path,
    command: str,
    *args: str,
    expected: int | Iterable[int] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    completed = subprocess.run(
        [sys.executable, str(KERNEL), command, "--adapter", str(adapter), *args],
        cwd=str(adapter.parent),
        env=child_env,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    if expected is not None:
        accepted = {expected} if isinstance(expected, int) else set(expected)
        if completed.returncode not in accepted:
            raise AssertionError(
                f"CLI return code {completed.returncode}, expected {sorted(accepted)}\n"
                f"command={command} {args!r}\n"
                f"stdout={completed.stdout}\n"
                f"stderr={completed.stderr}"
            )
    return completed


def evidence_writer_script(*, exit_code: int = 0, text: str = '{"ok":true}') -> str:
    return (
        "import os\n"
        "from pathlib import Path\n"
        "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
        f"(evidence / 'proof.json').write_text({text!r}, encoding='utf-8')\n"
        f"raise SystemExit({exit_code})\n"
    )


def make_case(
    case_id: str,
    category: str,
    *,
    argv: Sequence[str] | None = None,
    required: bool = True,
    platform: str = "any",
    depends_on: Sequence[str] = (),
    timeout_seconds: float = 10,
    required_files: Sequence[str] = ("proof.json",),
    non_empty_files: Sequence[str] = ("proof.json",),
) -> dict[str, Any]:
    return {
        "id": case_id,
        "category": category,
        "required": required,
        "platform": platform,
        "dependsOn": list(depends_on),
        "argv": list(argv or (sys.executable, "-c", evidence_writer_script())),
        "cwd": ".",
        "timeoutSeconds": timeout_seconds,
        "fixture": {"kind": "test-fixture", "description": "stdlib temporary fixture"},
        "externalCapabilities": [],
        "evidence": {
            "requiredFiles": list(required_files),
            "nonEmptyFiles": list(non_empty_files),
        },
    }


def write_manifest(project_root: Path, files: Sequence[str]) -> Path:
    return write_json(project_root / "source-manifest.json", {"files": list(files)})


def make_adapter(
    project_root: Path,
    cases: Sequence[dict[str, Any]],
    *,
    campaign_root: str = ".campaign",
    source_files: Sequence[str] = ("source.txt",),
    adapter_name: str = "adapter.json",
    coverage_mode: str | None = None,
) -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    for relative in source_files:
        source_path = project_root / relative
        source_path.parent.mkdir(parents=True, exist_ok=True)
        if not source_path.exists():
            source_path.write_text("stable source\n", encoding="utf-8")
    write_manifest(project_root, source_files)
    value = {
        "schemaVersion": 1,
        "projectId": "closed-loop-kernel-test",
        "projectRoot": ".",
        "campaignRoot": campaign_root,
        "source": {
            "provider": "manifest",
            "manifest": "source-manifest.json",
            "excludes": [campaign_root],
        },
        "localOnly": {
            "enabled": True,
            "allowedExternalCapabilities": [],
        },
        "cases": list(cases),
    }
    if coverage_mode is not None:
        value["coverageMode"] = coverage_mode
    return write_json(project_root / adapter_name, value)


def campaign_path(adapter: Path) -> Path:
    value = read_json(adapter)["campaignRoot"]
    path = Path(value)
    return path if path.is_absolute() else adapter.parent / path


def load_state(adapter: Path) -> dict[str, Any]:
    value = read_json(campaign_path(adapter) / "state.json")
    if not isinstance(value, dict):
        raise AssertionError("state.json is not an object")
    return value


def write_fix_for_latest_failure(
    adapter: Path,
    *,
    changed_files: Sequence[str] = (),
    external_condition: bool = True,
    name: str = "fix-audit.json",
) -> Path:
    state = load_state(adapter)
    failed_attempt: dict[str, Any] | None = None
    failed_run: dict[str, Any] | None = None
    for attempt in reversed(state["attempts"]):
        for case_run in reversed(attempt.get("caseRuns", [])):
            if case_run.get("status") == "FAILED":
                failed_attempt = attempt
                failed_run = case_run
                break
        if failed_run is not None:
            break
    if failed_attempt is None or failed_run is None:
        raise AssertionError("campaign has no failed case run")
    observed = json_output(run_cli(adapter, "status", expected=0))
    fixed_fingerprint = observed.get("currentObservedSourceFingerprint")
    if not isinstance(fixed_fingerprint, str):
        raise AssertionError(f"status lacks current source fingerprint: {observed!r}")
    return write_json(
        adapter.parent / name,
        {
            "failedCaseId": failed_run["caseId"],
            "failedRound": (
                failed_attempt["mode"]
                if failed_attempt["mode"] in {"quick", "regression"}
                else "initial"
            ),
            "failedAttemptId": failed_attempt["id"],
            "failedSourceFingerprint": failed_run["sourceFingerprint"],
            "fixedSourceFingerprint": fixed_fingerprint,
            "rootCause": "The temporary fixture selected the intentional failure branch.",
            "changedFiles": list(changed_files),
            "fixSummary": "Select the passing fixture branch for the targeted retest.",
            "externalCondition": external_condition,
            "minimalRegression": {"evidence": ["proof.json is recreated by the retest"]},
        },
    )
