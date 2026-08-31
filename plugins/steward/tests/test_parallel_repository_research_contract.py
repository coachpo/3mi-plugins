"""Contract tests for the shared parallel repository research skill."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PLUGIN_ROOT.parents[1]
SKILL = PLUGIN_ROOT / "skills" / "parallel-repository-research" / "SKILL.md"
AGENT = SKILL.parent / "agents" / "openai.yaml"
CODEX_ADAPTER = SKILL.parent / "references" / "codex.md"
CLAUDE_ADAPTER = SKILL.parent / "references" / "claude-code.md"
README = PLUGIN_ROOT / "README.md"
ROOT_README = REPOSITORY_ROOT / "README.md"
CODEX_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
CLAUDE_MARKETPLACE = REPOSITORY_ROOT / ".claude-plugin" / "marketplace.json"


def _frontmatter_fields(text: str) -> tuple[dict[str, str], str]:
    """Return scalar frontmatter fields and the Markdown body."""
    if not text.startswith("---\n"):
        raise AssertionError("SKILL.md must start with YAML frontmatter")
    metadata, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raise AssertionError("SKILL.md frontmatter is not closed")
    fields: dict[str, str] = {}
    for line in metadata.splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key] = value.strip()
    return fields, body


def _normalized(text: str) -> str:
    """Normalize prose wrapping while retaining semantic punctuation."""
    return re.sub(r"\s+", " ", text.lower())


def _section(markdown: str, heading: str) -> str:
    """Return one Markdown section without depending on its prose wording."""
    marker = f"{heading}\n"
    _, separator, remainder = markdown.partition(marker)
    if not separator:
        raise AssertionError(f"missing section: {heading}")
    next_heading = re.search(r"\n#{1,6} ", remainder)
    return remainder if next_heading is None else remainder[: next_heading.start()]


def _field_names(markdown: str, heading: str) -> set[str]:
    """Return backtick-delimited field names from a contract section."""
    return set(re.findall(r"(?m)^- `([^`]+)`:", _section(markdown, heading)))


class ParallelRepositoryResearchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.agent = AGENT.read_text(encoding="utf-8")
        cls.codex_adapter = CODEX_ADAPTER.read_text(encoding="utf-8")
        cls.claude_adapter = CLAUDE_ADAPTER.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")

    def test_skill_has_standard_metadata_and_two_public_host_entrypoints(self) -> None:
        fields, _ = _frontmatter_fields(self.skill)

        self.assertEqual({"name", "description"}, fields.keys())
        self.assertEqual("parallel-repository-research", fields["name"])
        self.assertRegex(fields["description"], r"(?i)(two|multiple).*(lane|branch)")
        self.assertRegex(
            fields["description"],
            r"(?i)(locat|map|inventor|dependenc|repository research)",
        )
        self.assertRegex(
            self.agent,
            r'(?m)^\s*display_name:\s*"Parallel Repository Research"\s*$',
        )
        self.assertRegex(
            self.agent,
            r'(?m)^\s*short_description:\s*"并行只读拆分代码库调研并汇总可核验证据"\s*$',
        )
        self.assertIn("$steward:parallel-repository-research", self.agent)
        self.assertIn("$steward:parallel-repository-research", self.skill)
        self.assertIn("/steward:parallel-repository-research", self.skill)
        self.assertRegex(self.agent, r"(?m)^\s*allow_implicit_invocation:\s*true\s*$")

    def test_shared_skill_routes_to_exactly_one_host_specific_adapter(self) -> None:
        adapter_section = _section(self.skill, "## Select one host adapter")
        reference_targets = set(
            re.findall(r"\]\((references/[^)]+)\)", adapter_section)
        )

        self.assertEqual(
            {"references/codex.md", "references/claude-code.md"},
            reference_targets,
        )
        for adapter_detail in (
            "gpt-5.6-luna",
            "fork_turns",
            "model: haiku",
            "very thorough",
            "Explore subagent",
        ):
            self.assertNotIn(adapter_detail, self.skill)
        self.assertIn("gpt-5.6-luna", self.codex_adapter)
        self.assertIn("fork_turns", self.codex_adapter)
        self.assertNotIn("gpt-5.6-luna", self.claude_adapter)
        self.assertIn("Explore", self.claude_adapter)
        self.assertIn("model: haiku", self.claude_adapter)

    def test_frozen_worker_contract_has_bounded_retry_and_all_constraints(self) -> None:
        self.assertEqual(
            {
                "laneId",
                "required",
                "crossCheckOf",
                "targetRoot",
                "researchGoal",
                "include",
                "exclude",
                "sourceBinding",
                "laneObjective",
                "applicableInstructions",
                "evidenceBudget",
                "outputContract",
                "constraints",
            },
            _field_names(self.skill, "### Worker input contract"),
        )
        plan = _section(self.skill, "## Freeze one research plan")
        for invariant in (
            "`required`",
            "`crossCheckOf`",
            "`planSealed=true`",
        ):
            self.assertIn(invariant, plan)
        worker_contract = _section(self.skill, "### Worker input contract")
        for invariant in (
            "`maxAttempts=2`",
            "`retryOn=transient-only`",
            "`read-only`",
            "`no-network`",
            "`no-secrets`",
            "`no-delegation`",
        ):
            self.assertIn(invariant, worker_contract)

    def test_delegation_requires_mechanical_isolation_or_sequential_fallback(
        self,
    ) -> None:
        route = _section(self.skill, "## Select one host adapter")
        self.assertIn(
            "`delegationGate=mechanical-read-only-no-network`",
            route,
        )
        self.assertIn("`fallbackRoute=sequential`", route)
        self.assertLess(route.index("mechanically restricts"), route.index("Otherwise"))
        for adapter in (self.codex_adapter, self.claude_adapter):
            lower = _normalized(adapter)
            self.assertIn("mechanically", lower)
            self.assertIn("network", lower)
            self.assertIn("sequential fallback", lower)

    def test_host_controls_keep_native_casing_and_meanings(self) -> None:
        combined = f"{self.skill}\n{self.codex_adapter}\n{self.claude_adapter}"
        execution_fields = _field_names(self.skill, "### Execution record")

        self.assertEqual(
            {
                "adapter",
                "route",
                "workerModel",
                "reasoning_effort",
                "searchDepth",
                "attempts",
                "readOnlyEnforcement",
                "toolLimitations",
                "fallbackReason",
            },
            execution_fields,
        )
        self.assertNotIn("reasoningEffort", combined)
        for effort in ("low", "medium", "high", "xhigh", "max"):
            self.assertRegex(self.codex_adapter, rf"\b{effort}\b")
        for depth in ("quick", "medium", "very thorough"):
            self.assertIn(depth, self.claude_adapter)
        self.assertIn("is not a reasoning-effort setting", self.claude_adapter)

    def test_lane_and_aggregate_schemas_fail_closed_on_required_lane_gaps(
        self,
    ) -> None:
        self.assertEqual(
            {
                "laneId",
                "status",
                "sourceBinding",
                "directAnswer",
                "evidence",
                "searched",
                "unsearched",
                "conflicts",
                "gaps",
                "stoppingReason",
                "execution",
            },
            _field_names(self.skill, "## Return the fixed lane result"),
        )
        self.assertEqual(
            {
                "status",
                "directAnswer",
                "evidence",
                "searched",
                "unsearched",
                "conflicts",
                "gaps",
                "laneResults",
                "executionSummary",
            },
            _field_names(self.skill, "## Verify and aggregate"),
        )
        aggregate = _normalized(_section(self.skill, "## Verify and aggregate"))
        for status in ("complete", "partial", "blocked", "drifted"):
            self.assertRegex(aggregate, rf"\b{status}\b")
        self.assertIn("every required lane is complete", aggregate)
        self.assertIn("any required lane is not complete", aggregate)
        self.assertIn("do not synthesize invalidated evidence", aggregate)
        plan = _normalized(_section(self.skill, "## Freeze one research plan"))
        self.assertIn("maxconcurrent", plan)
        self.assertIn("batchcount", plan)

    def test_result_stays_repository_research_not_semantic_review(self) -> None:
        lower = _normalized(self.skill)

        self.assertIn("review-semantic-risks", lower)
        for semantic_review_term in (
            "rf-*",
            "severity",
            "counterexamples",
            "campaign cases",
        ):
            self.assertIn(semantic_review_term, lower)

    def test_release_surfaces_describe_the_same_nine_skill_version(self) -> None:
        codex = json.loads(CODEX_MANIFEST.read_text(encoding="utf-8"))
        claude = json.loads(CLAUDE_MANIFEST.read_text(encoding="utf-8"))
        root_readme = ROOT_README.read_text(encoding="utf-8")
        marketplace = json.loads(CLAUDE_MARKETPLACE.read_text(encoding="utf-8"))
        marketplace_steward = next(
            plugin for plugin in marketplace["plugins"] if plugin["name"] == "steward"
        )
        skill_names = {
            path.parent.name for path in (PLUGIN_ROOT / "skills").glob("*/SKILL.md")
        }

        self.assertEqual("0.0.11", codex["version"])
        self.assertEqual(codex["version"], claude["version"])
        self.assertEqual(9, len(skill_names))
        self.assertIn("analyze-change-request", skill_names)
        self.assertIn("parallel-repository-research", skill_names)
        for public_description in (
            codex["description"],
            codex["interface"]["longDescription"],
            claude["description"],
            marketplace_steward["description"],
            root_readme,
            self.readme,
        ):
            self.assertIn("九", public_description)
        self.assertIn("变更请求", codex["interface"]["longDescription"])
        self.assertIn("并行只读", codex["interface"]["longDescription"])

        routing_paragraph = next(
            paragraph
            for paragraph in self.readme.split("\n\n")
            if "隐式" in paragraph and "write-agent-guides" in paragraph
        )
        self.assertIn("parallel-repository-research", routing_paragraph)
        self.assertRegex(routing_paragraph, r"其余七个.*显式|七个.*显式")


if __name__ == "__main__":
    unittest.main()
