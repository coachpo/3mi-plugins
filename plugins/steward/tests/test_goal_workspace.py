"""Regression coverage for GOAL workspace creator preflight."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_SCRIPT = PLUGIN_ROOT / "scripts" / "goal_workspace.py"


class GoalWorkspacePreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = (
            "Cloudflare Workers API Server：为单门店到店自取订餐产品交付可运行、"
            "可迁移、可测试且有明确 HTTP 契约的纯后端 API，完整实现当前产品规格"
            "中的菜单、无账号顾客下单与私密查单、员工认证与商品及订单处理、"
            "线下收款业务闭环"
        )
        self.expected_path = (
            ".steward/goal-context/cloudflare-workers-api-server-http-api.md"
        )

    def _payload(self, context_path: str) -> bytes:
        objective = "\n".join(
            (
                "结果：" + self.result,
                "证据与上下文：已核实背景见 " + context_path,
                "范围：只交付纯 API Server",
                "约束与授权：不部署或发布",
                "完成标准：(C1) API 行为通过自动化测试验证",
                "正当阻塞项：缺少必要且无法替代的平台能力时停止",
                "最终交付：源码、迁移、测试和验证报告",
            )
        )
        return json.dumps(
            {
                "objective": objective,
                "context": {
                    "path": context_path,
                    "content": "# 已核实来源\n\n产品规格。\n",
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _preflight(self, payload: bytes) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(WORKSPACE_SCRIPT), "validate-create", "-"],
            input=payload,
            capture_output=True,
            check=False,
        )

    def test_preflight_reports_complete_path_derived_from_result(self) -> None:
        result = self._preflight(
            self._payload(".steward/goal-context/cloudflare-workers-api-server.md")
        )

        self.assertEqual(1, result.returncode)
        self.assertIn(b"WORKSPACE_CONTEXT_PATH", result.stderr)
        self.assertIn(self.expected_path.encode("utf-8"), result.stderr)
        self.assertEqual(b"", result.stdout)

    def test_preflight_accepts_exact_creator_payload_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, str(WORKSPACE_SCRIPT), "validate-create", "-"],
                input=self._payload(self.expected_path),
                cwd=temporary,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr.decode())
            view = json.loads(result.stdout)
            self.assertEqual(self.expected_path, view["context"]["path"])
            result_line = view["goalContract"]["objective"].split("\n")[0]
            self.assertEqual(self.result, result_line[3:])
            self.assertFalse((Path(temporary) / ".steward").exists())

    @unittest.skipIf(os.name == "nt", "creating symlinks requires extra Windows privileges")
    def test_view_ignores_legacy_verification_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "project"
            subprocess.run(
                ["git", "init", "-q", str(root)],
                check=True,
                capture_output=True,
            )
            created = subprocess.run(
                [sys.executable, str(WORKSPACE_SCRIPT), "create", str(root), "-"],
                input=self._payload(self.expected_path),
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, created.returncode, created.stderr.decode())

            legacy_root = root / ".steward" / "verification" / "campaign"
            legacy_root.mkdir(parents=True)
            legacy_target = base / "legacy-state.json"
            legacy_target.write_text("{}\n", encoding="utf-8")
            (legacy_root / "state.json").symlink_to(legacy_target)

            viewed = subprocess.run(
                [sys.executable, str(WORKSPACE_SCRIPT), "view", str(root)],
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, viewed.returncode, viewed.stderr.decode())
            self.assertEqual(json.loads(created.stdout), json.loads(viewed.stdout))


if __name__ == "__main__":
    unittest.main()
