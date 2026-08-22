"""Tests for the shared seven-line consensus GOAL contract."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "goal_contract.py"
SCHEMA = PLUGIN_ROOT / "references" / "goal-contract-v1.schema.json"
TEMPLATE = PLUGIN_ROOT / "references" / "goal-template.txt"
AUTHORING = PLUGIN_ROOT / "references" / "goal-authoring.md"
DRAFT_SKILL = PLUGIN_ROOT / "skills" / "draft-consensus-goal" / "SKILL.md"
START_SKILL = PLUGIN_ROOT / "skills" / "start-consensus-goal" / "SKILL.md"
DRAFT_AGENT = (
    PLUGIN_ROOT / "skills" / "draft-consensus-goal" / "agents" / "openai.yaml"
)
START_AGENT = (
    PLUGIN_ROOT / "skills" / "start-consensus-goal" / "agents" / "openai.yaml"
)
PLUGIN_README = PLUGIN_ROOT / "README.md"

SPEC = importlib.util.spec_from_file_location("steward_goal_contract", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import setup guard
    raise RuntimeError("cannot load goal_contract.py")
goal_contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = goal_contract
SPEC.loader.exec_module(goal_contract)


EXPECTED_TEMPLATE = """结果：[用户可见的最终结果]
证据与上下文：[相关文件、规范、错误、数据和必需来源]
范围：[必须完成的工作、需要保留的行为和明确排除项]
约束与授权：[架构、兼容性、安全、隐私、性能、项目约定、允许的本地操作和需要确认的操作]
完成标准：[(C1) 第一项可执行完成标准；(C2) 第二项可执行完成标准；按需继续连续编号]
正当阻塞项：[缺少哪些证据、访问权、授权或外部状态时可以停止]
最终交付：[需要报告的变更、验证证据、假设、风险和剩余缺口]
"""


def rendered_goal(
    *,
    result: str = "用户可以使用已验证的结果",
    evidence: str = "仓库事实与用户已接受的决定",
    scope: str = "完成请求内工作并保留既有行为",
    constraints: str = "只执行已授权的本地非破坏性操作",
    criteria: str = "(C1) 单元测试通过；(C2) 契约检查通过",
    blockers: str = "缺少必要访问权或外部状态时停止",
    delivery: str = "按 C* 报告结果、证据、风险和缺口",
) -> str:
    return "\n".join(
        (
            "结果：" + result,
            "证据与上下文：" + evidence,
            "范围：" + scope,
            "约束与授权：" + constraints,
            "完成标准：" + criteria,
            "正当阻塞项：" + blockers,
            "最终交付：" + delivery,
        )
    )


class GoalContractTests(unittest.TestCase):
    def assert_invalid(self, value: str | bytes, code: str | None = None) -> None:
        with self.assertRaises(goal_contract.GoalContractError) as raised:
            goal_contract.validate_goal_text(value)
        if code is not None:
            self.assertEqual(code, raised.exception.code)

    def test_template_is_exact_canonical_seven_line_schema(self) -> None:
        data = TEMPLATE.read_bytes()
        self.assertEqual(EXPECTED_TEMPLATE.encode("utf-8"), data)
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.endswith(b"\n"))
        self.assertEqual(7, len(data.decode("utf-8").splitlines()))
        self.assertEqual(
            [label for _key, label in goal_contract.FIELD_SPECS],
            [line.split("：", 1)[0] for line in EXPECTED_TEMPLATE.splitlines()],
        )
        for placeholder in EXPECTED_TEMPLATE.splitlines():
            self.assertRegex(placeholder, r"：\[.+\]$")

    def test_valid_goal_parses_fields_and_contiguous_criteria(self) -> None:
        value = rendered_goal()
        contract = goal_contract.validate_goal_text(value)
        self.assertEqual(value, contract.objective)
        self.assertEqual(7, len(contract.fields))
        self.assertEqual(
            ["C1", "C2"], [item.id for item in contract.completion_criteria]
        )
        self.assertEqual("单元测试通过", contract.completion_criteria[0].text)

    def test_single_criterion_and_wu_are_valid(self) -> None:
        value = rendered_goal(
            evidence="无",
            constraints="无",
            criteria="(C1) 人工评审确认结果",
            blockers="无",
        )
        contract = goal_contract.validate_goal_text(value)
        self.assertEqual(("C1",), tuple(item.id for item in contract.completion_criteria))

    def test_result_scope_and_final_delivery_require_substantive_content(self) -> None:
        invalid_values = (
            rendered_goal(result="无"),
            rendered_goal(scope="无"),
            rendered_goal(delivery="无"),
        )
        for value in invalid_values:
            with self.subTest(value=value):
                self.assert_invalid(value, "GOAL_FIELD_VALUE")

    def test_ordinary_semicolons_and_legitimate_brackets_are_valid(self) -> None:
        value = rendered_goal(
            evidence='运行 argv=["python3","-m","unittest"]',
            criteria="(C1) 运行测试；检查输出为 PASS；(C2) 运行审计",
        )
        contract = goal_contract.validate_goal_text(value)
        self.assertEqual(
            "运行测试；检查输出为 PASS", contract.completion_criteria[0].text
        )
        goal_contract.validate_goal_text(
            rendered_goal(
                result="保留 [section]、TODO 列表、/项目/🚀 和 👩‍💻 的既有语义"
            )
        )

    def test_terminal_lf_is_transport_and_has_same_view_and_digest(self) -> None:
        value = rendered_goal()
        plain = goal_contract.validate_goal_text(value)
        framed = goal_contract.validate_goal_text(value + "\n")
        self.assertEqual(plain, framed)
        self.assertEqual(
            goal_contract.canonical_goal_contract_bytes(plain),
            goal_contract.canonical_goal_contract_bytes(framed),
        )
        self.assertEqual(
            goal_contract.goal_contract_sha256(plain),
            goal_contract.goal_contract_sha256(framed),
        )

    def test_rejects_schema_drift_and_wrappers(self) -> None:
        valid = rendered_goal()
        lines = valid.splitlines()
        cases = {
            "six": "\n".join(lines[:-1]),
            "eight": valid + "\n附加：文本",
            "blank": "\n".join(lines[:2] + [""] + lines[3:]),
            "reordered": "\n".join([lines[1], lines[0], *lines[2:]]),
            "renamed": valid.replace("结果：", "成果：", 1),
            "duplicated": "\n".join([lines[0], lines[0], *lines[2:]]),
            "ascii-colon": valid.replace("结果：", "结果:", 1),
            "heading": "# GOAL\n" + valid,
            "fence": "```\n" + valid + "\n```",
            "double-terminal-lf": valid + "\n\n",
            "empty-value": valid.replace(lines[0], "结果：", 1),
            "leading-space": valid.replace("结果：用户", "结果： 用户", 1),
            "trailing-space": valid.replace(lines[0], lines[0] + " ", 1),
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                self.assert_invalid(value)

    def test_rejects_noncanonical_encoding_and_line_separators(self) -> None:
        valid = rendered_goal()
        cases: tuple[str | bytes, ...] = (
            valid.replace("\n", "\r\n"),
            valid.replace("\n", "\v", 1),
            valid.replace("\n", "\f", 1),
            valid.replace("\n", "\x1c", 1),
            valid.replace("\n", "\x1d", 1),
            valid.replace("\n", "\x1e", 1),
            "\ufeff" + valid,
            valid + "\x00",
            valid.replace("\n", "\x85", 1),
            valid.replace("\n", "\u2028", 1),
            valid.replace("\n", "\u2029", 1),
            valid.replace("用户", "\ud800", 1),
            b"\xff\xfe",
        )
        for value in cases:
            with self.subTest(value=repr(value)[:40]):
                self.assert_invalid(value)

    def test_rejects_c0_c1_and_unicode_bidi_controls(self) -> None:
        controls = (
            "\x01",
            "\x07",
            "\x08",
            "\x1b",
            "\x7f",
            "\x80",
            "\x9b",
            "\u061c",
            "\u200e",
            "\u200f",
            "\u202a",
            "\u202e",
            "\u2066",
            "\u2069",
        )
        for control in controls:
            with self.subTest(control=ascii(control)):
                self.assert_invalid(
                    rendered_goal(constraints="本地" + control + "授权"),
                    "GOAL_CONTROL",
                )

    def test_rejects_only_complete_canonical_and_legacy_placeholder_values(self) -> None:
        for placeholder in goal_contract.KNOWN_PLACEHOLDERS:
            with self.subTest(placeholder=placeholder):
                self.assert_invalid(rendered_goal(result=placeholder))
                goal_contract.validate_goal_text(
                    rendered_goal(result="按字面处理 `" + placeholder + "` 文本")
                )
        for sentinel in goal_contract.PLACEHOLDER_ONLY_VALUES:
            with self.subTest(sentinel=sentinel):
                self.assert_invalid(rendered_goal(result=sentinel))
                self.assert_invalid(rendered_goal(result="[" + sentinel + "]"))
        for annotated in (
            "TODO: add test",
            "TBD ： 等待确认",
            "待确认：补充需求",
            "[TBD: 等待确认]",
            "<FIXME：add evidence>",
        ):
            with self.subTest(annotated=annotated):
                self.assert_invalid(rendered_goal(result=annotated))

    def test_allows_placeholder_and_criterion_tokens_as_literal_content(self) -> None:
        value = rendered_goal(
            result="删除 README 中的 `[TODO]` 标签并保留 [TBD: 示例] 文本",
            scope="只处理正文里的 [TODO]，不改同名代码标识符",
            criteria="(C1) 验证结果可以引用 `(C2)` 与 [TODO] 字面文本",
        )
        contract = goal_contract.validate_goal_text(value)
        self.assertEqual(("C1",), tuple(item.id for item in contract.completion_criteria))
        self.assertIn("`(C2)`", contract.completion_criteria[0].text)

        quoted = goal_contract.validate_goal_text(
            rendered_goal(
                criteria='(C1) 验证 “(C2)” 和 "phase (C3) reference" 以及 `阶段 (C4) 引用`'
            )
        )
        self.assertEqual(("C1",), tuple(item.id for item in quoted.completion_criteria))

        unquoted = goal_contract.validate_goal_text(
            rendered_goal(criteria="(C1) 证明(C2)只是本条标准中的字面引用")
        )
        self.assertEqual(("C1",), tuple(item.id for item in unquoted.completion_criteria))

    def test_length_boundary_counts_canonical_unicode_code_points(self) -> None:
        base = rendered_goal(result="x")
        exactly = rendered_goal(result="x" * (4_000 - len(base) + 1))
        self.assertEqual(4_000, len(exactly))
        self.assertEqual(exactly, goal_contract.validate_goal_text(exactly).objective)
        self.assertEqual(
            exactly,
            goal_contract.validate_goal_text(exactly + "\n").objective,
        )
        self.assert_invalid(exactly + "x", "GOAL_LENGTH")

    def test_bounded_reader_stops_before_consuming_oversized_input(self) -> None:
        stream = io.BytesIO(b"x" * (goal_contract.MAX_INPUT_BYTES + 100_000))
        with self.assertRaises(goal_contract.GoalContractError) as raised:
            goal_contract._read_bounded(stream)
        self.assertEqual("GOAL_LENGTH", raised.exception.code)
        self.assertEqual(goal_contract.MAX_INPUT_BYTES + 1, stream.tell())

        self.assert_invalid("x" * 100_000, "GOAL_LENGTH")
        self.assert_invalid(b"x" * (goal_contract.MAX_INPUT_BYTES + 1), "GOAL_LENGTH")

    def test_file_loader_rejects_symlinks_fifos_and_devices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            goal = root / "goal.txt"
            goal.write_text(rendered_goal(), encoding="utf-8")
            self.assertEqual(rendered_goal(), goal_contract.load_goal_contract(goal).objective)

            link = root / "goal-link.txt"
            try:
                link.symlink_to(goal)
            except (NotImplementedError, OSError) as exc:  # pragma: no cover - platform
                self.skipTest("symlink creation is unavailable: " + str(exc))
            with self.assertRaises(goal_contract.GoalContractError) as raised:
                goal_contract.load_goal_contract(link)
            self.assertEqual("GOAL_IO", raised.exception.code)

            if hasattr(os, "mkfifo"):
                fifo = root / "goal.fifo"
                os.mkfifo(fifo)
                checked = subprocess.run(
                    [sys.executable, str(SCRIPT), "check", str(fifo)],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=2,
                )
                self.assertEqual(2, checked.returncode, checked.stderr)
                self.assertTrue(checked.stderr.startswith("ERROR GOAL_IO:"))

            device = Path("/dev/null")
            if device.exists():
                checked = subprocess.run(
                    [sys.executable, str(SCRIPT), "check", str(device)],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=2,
                )
                self.assertEqual(2, checked.returncode, checked.stderr)
                self.assertTrue(checked.stderr.startswith("ERROR GOAL_IO:"))

    def test_criteria_ids_are_unique_contiguous_and_ordered(self) -> None:
        invalid_criteria = (
            "检查通过",
            "无",
            "(C0) 零",
            "(C01) 前导零",
            "(c1) 小写",
            "C1：错误格式",
            "(C1) 一；(C1) 重复",
            "(C1) 一；(C3) 跳号",
            "(C2) 二；(C1) 一",
            "(C1) 一 (C2) 缺少分隔符",
            "(C1) 测试通过 (C2) 契约通过",
            "(C1) 测试通过。(C2)契约通过",
            "(C1) 一；(C2) ",
            "(C1) TODO",
            "(C1) TODO: add test",
            "(C1) [TBD]",
            "(C1) [TBD: 等待确认]",
            "(C1) 无",
        )
        for value in invalid_criteria:
            with self.subTest(criteria=value):
                self.assert_invalid(rendered_goal(criteria=value))

    def test_canonical_view_and_digest_are_deterministic(self) -> None:
        contract = goal_contract.validate_goal_text(rendered_goal())
        view = goal_contract.goal_contract_view(contract)
        self.assertEqual("steward.goal-contract", view["schemaId"])
        self.assertEqual(1, view["schemaVersion"])
        self.assertEqual(["C1", "C2"], [item["id"] for item in view["completionCriteria"]])
        expected_bytes = json.dumps(
            view,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(expected_bytes, goal_contract.canonical_goal_contract_bytes(contract))
        digest = goal_contract.goal_contract_sha256(contract)
        self.assertEqual(
            "sha256:da63c6f10bed3c9be96065d5e1811d75d961c25e3882778623bc9da4b1436c39",
            digest,
        )
        self.assertEqual(digest, goal_contract.goal_contract_sha256(contract))

    def test_view_round_trip_rejects_schema_and_derived_data_tampering(self) -> None:
        contract = goal_contract.validate_goal_text(rendered_goal())
        view = goal_contract.goal_contract_view(contract)
        self.assertEqual(contract, goal_contract.validate_goal_contract_view(view))

        inconsistent_contract = goal_contract.GoalContract(
            objective=contract.objective,
            fields=contract.fields[:-1],
            completion_criteria=contract.completion_criteria,
        )
        with self.assertRaises(goal_contract.GoalContractError):
            goal_contract.goal_contract_view(inconsistent_contract)

        mutations = []
        unknown = dict(view)
        unknown["unknown"] = True
        mutations.append(unknown)
        wrong_version = dict(view)
        wrong_version["schemaVersion"] = 2
        mutations.append(wrong_version)
        changed_fields = json.loads(json.dumps(view, ensure_ascii=False))
        changed_fields["fields"][0]["value"] = "漂移"
        mutations.append(changed_fields)
        changed_criteria = json.loads(json.dumps(view, ensure_ascii=False))
        changed_criteria["completionCriteria"][0]["id"] = "C9"
        mutations.append(changed_criteria)

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(goal_contract.GoalContractError):
                    goal_contract.validate_goal_contract_view(mutation)

    def test_schema_resource_matches_view_identity_and_field_order(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            "steward.goal-contract",
            schema["properties"]["schemaId"]["const"],
        )
        self.assertEqual(1, schema["properties"]["schemaVersion"]["const"])
        self.assertEqual(4000, schema["properties"]["objective"]["maxLength"])
        objective_pattern = schema["properties"]["objective"]["pattern"]
        for escaped_separator in (
            r"\u0000-\u001F",
            r"\u007F-\u009F",
            r"\u061C",
            r"\u200E",
            r"\u200F",
            r"\u2028-\u202E",
            r"\u2066-\u2069",
        ):
            self.assertIn(escaped_separator, objective_pattern)
        self.assertNotIn("$", objective_pattern)
        criterion_id_pattern = schema["properties"]["completionCriteria"]["items"][
            "properties"
        ]["id"]["pattern"]
        self.assertNotIn("$", criterion_id_pattern)
        prefix_items = schema["properties"]["fields"]["prefixItems"]
        self.assertEqual(7, len(prefix_items))
        for (key, label), item in zip(goal_contract.FIELD_SPECS, prefix_items):
            definition = schema["$defs"][item["$ref"].removeprefix("#/$defs/")]
            constants = definition["allOf"][1]["properties"]
            self.assertEqual(key, constants["key"]["const"])
            self.assertEqual(label, constants["label"]["const"])
            if key in goal_contract.REQUIRED_SUBSTANTIVE_FIELD_KEYS:
                self.assertEqual("无", constants["value"]["not"]["const"])
            else:
                self.assertNotIn("value", constants)

        objective_re = re.compile(objective_pattern)
        self.assertIsNotNone(objective_re.search(rendered_goal()))
        for invalid in (
            rendered_goal() + "\n",
            rendered_goal().replace("用户", "用户\x00", 1),
            rendered_goal().replace("用户", "用户\x1b", 1),
            rendered_goal().replace("用户", "用户\x9b", 1),
            rendered_goal().replace("用户", "用户\v", 1),
            rendered_goal().replace("用户", "用户\u2028", 1),
            rendered_goal().replace("用户", "用户\u202e", 1),
            rendered_goal().replace("用户", "用户\u2066", 1),
        ):
            self.assertIsNone(objective_re.search(invalid))
        criterion_id_re = re.compile(criterion_id_pattern)
        self.assertIsNotNone(criterion_id_re.search("C1"))
        self.assertIsNone(criterion_id_re.search("C1\n"))

    def test_cli_modes_are_deterministic_and_read_only(self) -> None:
        value = rendered_goal() + "\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "GOAL.txt"
            path.write_text(value, encoding="utf-8")
            before = path.read_bytes()

            check = subprocess.run(
                [sys.executable, str(SCRIPT), "check", str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
            view = subprocess.run(
                [sys.executable, str(SCRIPT), "view", str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
            digest = subprocess.run(
                [sys.executable, str(SCRIPT), "digest", "-"],
                input=value,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, check.returncode, check.stderr)
            self.assertRegex(check.stdout, r"^VALID sha256:[0-9a-f]{64}\n$")
            self.assertEqual(0, view.returncode, view.stderr)
            self.assertEqual(
                goal_contract.goal_contract_view(
                    goal_contract.validate_goal_text(value)
                ),
                json.loads(view.stdout),
            )
            self.assertEqual(0, digest.returncode, digest.stderr)
            self.assertEqual(check.stdout.removeprefix("VALID "), digest.stdout)
            self.assertEqual(before, path.read_bytes())

    def test_cli_reports_validation_and_io_errors(self) -> None:
        invalid = subprocess.run(
            [sys.executable, str(SCRIPT), "check", "-"],
            input="不是 GOAL",
            text=True,
            capture_output=True,
            check=False,
        )
        missing = subprocess.run(
            [sys.executable, str(SCRIPT), "check", "/definitely/missing/GOAL.txt"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, invalid.returncode)
        self.assertTrue(invalid.stderr.startswith("ERROR GOAL_"))
        self.assertEqual(2, missing.returncode)
        self.assertTrue(missing.stderr.startswith("ERROR GOAL_IO:"))

    def test_both_skills_share_validator_contract_but_keep_tool_semantics(self) -> None:
        draft = DRAFT_SKILL.read_text(encoding="utf-8")
        start = START_SKILL.read_text(encoding="utf-8")
        authoring = AUTHORING.read_text(encoding="utf-8")

        for skill in (draft, start):
            self.assertEqual(1, skill.count("../../references/goal-authoring.md"))
        self.assertEqual(1, authoring.count("](goal-template.txt)"))
        self.assertEqual(1, authoring.count("scripts/goal_contract.py"))
        self.assertIn("`(C1) ...；(C2) ...`", authoring)
        self.assertIn("4,000 Unicode code points", authoring)
        self.assertIn("same failure repeats", authoring)
        self.assertIn("only when the user accepted that item", authoring)

        self.assertIn("never calls `get_goal`, `create_goal`, or `update_goal`", draft)
        self.assertIn("call `get_goal` before", start)
        self.assertIn("drafting or executing anything", start)
        self.assertLess(start.index("call `get_goal`"), start.index("goal-authoring.md"))
        self.assertIn("strict v1", start)
        self.assertIn("carries stable `C*`", start)
        self.assertIn("A classification failure is not permission to replace it", start)
        self.assertIn("Create a new Goal with the validator's canonical `objective` exactly", start)
        self.assertIn("compatible legacy Goal", start)
        self.assertIn("original completion contract", start)

    def test_start_skill_covers_steering_resume_and_current_evidence(self) -> None:
        start = START_SKILL.read_text(encoding="utf-8")
        self.assertIn("latest `status` and complete `objective`", start)
        self.assertIn("only state authority", start)
        self.assertIn("If the read fails, do not create, update, or execute a Goal", start)
        self.assertIn("resume, finish, status, or explanation request does not authorize creation", start)
        self.assertIn("A paused Goal or a blocked Goal not restored by the host is report-only", start)
        self.assertIn("complete Goal is not repeated", start)
        self.assertIn("Ask one necessary question", start)
        self.assertIn("for a material conflict", start)
        self.assertIn("Before each major phase", start)
        self.assertIn("before any `update_goal`", start)
        self.assertIn("`get_goal`", start)
        self.assertIn("again. Stop", start)
        self.assertIn("If the objective changed", start)
        self.assertIn("never complete a changed Goal with stale evidence", start)
        self.assertIn("evidence obtained after the latest relevant change", start)
        self.assertIn("every `C*` and the current objective digest", start)
        self.assertIn("Mark it complete only after every", start)
        self.assertIn("criterion is verified", start)
        self.assertIn("Mark blocked only when the current Goal", start)
        self.assertIn("tool's blocking threshold", start)

    def test_agent_metadata_advertises_machine_validation_and_stable_ids(self) -> None:
        for path in (DRAFT_AGENT, START_AGENT):
            text = path.read_text(encoding="utf-8")
            self.assertIn("机器校验", text)
            self.assertIn("C*", text)
            self.assertIn("七行", text)
            self.assertIn("allow_implicit_invocation: false", text)

        start_agent = START_AGENT.read_text(encoding="utf-8")
        self.assertIn("创建机器校验", start_agent)
        self.assertIn("当前机器状态恢复兼容的活动 Goal", start_agent)
        self.assertIn("验证完成或正当阻塞", start_agent)

    def test_start_public_surfaces_advertise_restore_resume_and_state_gates(self) -> None:
        start = START_SKILL.read_text(encoding="utf-8")
        readme = PLUGIN_README.read_text(encoding="utf-8")
        self.assertIn("resume a compatible active Goal", start)
        self.assertIn("strict v1", start)
        self.assertIn("carries stable `C*`", start)
        self.assertIn("compatible legacy Goal", start)
        self.assertIn("恢复、续跑、完成兼容的现有 Goal", readme)
        self.assertIn("paused 或未恢复的 blocked Goal 只报告状态", readme)
        self.assertIn("最新 status 和 objective 都是恢复与续跑的事实源", readme)
        self.assertIn("成功返回 null 也不会把仅恢复/续跑请求升级为创建授权", readme)
        self.assertIn("新建或严格通过版本 1 合同的 Goal 按稳定 `C*`", readme)
        self.assertIn("兼容的 legacy Goal 即使没有 `C*` 也只按其原合同", readme)


if __name__ == "__main__":
    unittest.main()
