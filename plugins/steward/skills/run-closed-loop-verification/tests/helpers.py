from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
PLUGIN_SCRIPTS = SKILL_ROOT.parents[1] / "scripts"
CAMPAIGN = SCRIPTS / "campaign.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

from goal_contract import goal_contract_sha256, load_goal_contract


def goal_text(criteria: str = "(C1) 命令通过并产生证明") -> str:
    return "\n".join(
        [
            "结果：交付经过验证的本地实现",
            "证据与上下文：仓库文件和本地命令；补充背景见 .steward/goal-context/goal-context.md",
            "范围：当前测试项目",
            "约束与授权：仅执行本地确定性命令",
            "完成标准：" + criteria,
            "正当阻塞项：缺少本地运行环境",
            "最终交付：实现、回归结果和审计证据",
        ]
    )


def passing_command() -> list[str]:
    return [
        sys.executable,
        "-c",
        "import os,pathlib; pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'],'proof.txt').write_text('ok',encoding='utf-8')",
    ]


def marker_command() -> list[str]:
    return [
        sys.executable,
        "-c",
        (
            "import os,pathlib,sys; "
            "ok=pathlib.Path('app.txt').read_text(encoding='utf-8').strip()=='good'; "
            "pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'],'proof.txt').write_text('ok',encoding='utf-8') if ok else None; "
            "sys.exit(0 if ok else 1)"
        ),
    ]


def make_project(
    root: Path,
    *,
    criteria: str = "(C1) 命令通过并产生证明",
    command: list[str] | None = None,
    required: bool = True,
    platform: str = "any",
) -> Path:
    root.mkdir(parents=True)
    steward = root / ".steward"
    steward.mkdir()
    (steward / ".gitignore").write_bytes(b"*\n")
    (steward / "goal-context").mkdir()
    (steward / "goal-context" / "goal-context.md").write_text(
        "# 已核实背景\n\n- 当前测试请求与仓库文件。\n", encoding="utf-8"
    )
    (steward / "goal.txt").write_text(goal_text(criteria) + "\n", encoding="utf-8")
    (root / "app.txt").write_text("good\n", encoding="utf-8")
    goal_digest = goal_contract_sha256(load_goal_contract(steward / "goal.txt"))
    adapter = {
        "schemaVersion": 2,
        "source": {
            "provider": "files",
            "files": ["app.txt"],
            "excludes": [".steward"],
        },
        "goalContract": {
            "path": ".steward/goal.txt",
            "contractVersion": 1,
            "sha256": goal_digest,
        },
        "cases": [
            {
                "id": "acceptance",
                "required": required,
                "platform": platform,
                "coversCriteria": ["C1"],
                "argv": command or passing_command(),
                "cwd": ".",
                "timeoutSeconds": 30,
                "evidence": {
                    "requiredFiles": ["proof.txt"],
                    "nonEmptyFiles": ["proof.txt"],
                },
            }
        ],
    }
    path = steward / "project-adapter.json"
    write_json(path, adapter)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Verifier Tests"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "verifier@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "app.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "test fixture"], check=True
    )
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def mutate_adapter(path: Path, callback: Any) -> None:
    value = read_json(path)
    callback(value)
    write_json(path, value)


def run_cli(
    adapter: Path, command: str, *arguments: str
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(CAMPAIGN),
            command,
            "--adapter",
            str(adapter),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def clone(value: Any) -> Any:
    return copy.deepcopy(value)
