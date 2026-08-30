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


class ParallelRepositoryResearchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.agent = AGENT.read_text(encoding="utf-8")
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

    def test_current_session_model_coordinates_codex_luna_workers(self) -> None:
        lower = _normalized(self.skill)

        self.assertRegex(lower, r"current (main[- ]session|main|session) model")
        self.assertRegex(lower, r"coordinat(or|es|ing)")
        self.assertRegex(lower, r"do not.{0,80}(particular|fixed) coordinator model")
        self.assertRegex(lower, r"spawn each lane.{0,80}gpt-5\.6-luna")
        for effort in ("low", "medium", "high", "xhigh", "max"):
            self.assertRegex(lower, rf"\b{effort}\b")
        self.assertRegex(lower, r"fork_turns.{0,30}\"none\"")
        self.assertRegex(lower, r"fork_turns.*(positive|minimal|smallest)")
        self.assertRegex(
            lower,
            r"never.{0,80}(omit.{0,60}fork_turns|use.{0,20}\"all\")",
        )

    def test_claude_explore_depth_is_distinct_from_codex_reasoning_effort(self) -> None:
        lower = _normalized(self.skill)

        self.assertIn("explore", lower)
        self.assertRegex(lower, r"model\s*:\s*[`\"']?haiku")
        self.assertIn("searchdepth", lower)
        for depth in ("quick", "medium", "very thorough"):
            self.assertIn(depth, lower)
        self.assertRegex(
            lower,
            r"searchdepth.{0,180}(not|isn't|is not).{0,100}(reasoning|effort)",
        )
        self.assertRegex(lower, r"explore.{0,500}(self-contained|restate|repeat)")

    def test_lane_planning_respects_capacity_and_has_a_sequential_fallback(
        self,
    ) -> None:
        lower = _normalized(self.skill)

        self.assertRegex(
            lower,
            r"(single-point|single point|single-symbol|single symbol)",
        )
        self.assertRegex(
            lower,
            r"(do not|must not|never).{0,80}(fan out|spawn|delegate)",
        )
        self.assertRegex(lower, r"(slot|capacity|concurren)")
        self.assertRegex(lower, r"(batch|wave)")
        self.assertRegex(
            lower,
            r"(without|do not|must not|never).{0,100}(duplicat|repeat).{0,60}lane",
        )
        self.assertRegex(lower, r"(sequential|serial).{0,100}(fallback|search|lane)")
        self.assertRegex(
            lower,
            r"worker.{0,120}(do not|must not|never).{0,100}(delegate|spawn)",
        )

        for input_field in (
            "targetRoot",
            "researchGoal",
            "include",
            "exclude",
            "laneObjective",
            "evidenceBudget",
            "outputContract",
        ):
            self.assertIn(input_field, self.skill)
        self.assertRegex(self.skill, r"(?i)(baseline|diff)")

    def test_worker_output_is_evidence_bearing_and_not_a_semantic_review(self) -> None:
        lower = _normalized(self.skill)

        for status in ("complete", "partial", "blocked", "drifted"):
            self.assertRegex(lower, rf"\b{status}\b")
        for output_field in (
            "directAnswer",
            "evidence",
            "searched",
            "unsearched",
            "conflicts",
            "gaps",
            "adapter",
        ):
            self.assertIn(output_field, self.skill)
        self.assertRegex(lower, r"path:line|project-relative")
        self.assertRegex(
            lower,
            r"(coordinator|main model).*(verify|deduplic|conflict|synthesi)",
        )
        self.assertIn("review-semantic-risks", lower)
        for semantic_review_term in (
            "rf-*",
            "severity",
            "counterexample",
            "campaign case",
        ):
            self.assertIn(semantic_review_term, lower)
        self.assertRegex(
            lower,
            r"(finding|severity).{0,120}rf-\*.{0,120}campaign case"
            r".{0,100}belong to.{0,80}review-semantic-risks",
        )

    def test_read_only_enforcement_is_reported_without_overclaiming(self) -> None:
        lower = _normalized(self.skill)

        self.assertRegex(lower, r"must not:.{0,100}(create|edit|delete).{0,150}files")
        self.assertRegex(lower, r"run project code.{0,80}tests.{0,80}builds")
        self.assertRegex(lower, r"package managers.{0,80}installers")
        self.assertRegex(
            lower,
            r"git writes.{0,80}network requests.{0,80}external-service",
        )
        self.assertRegex(lower, r"(seek|copy|return).{0,80}secret values")
        self.assertIn("sandbox", lower)
        self.assertIn("tool-restricted", lower)
        self.assertIn("instruction-only", lower)
        self.assertRegex(
            lower,
            r"never.{0,100}prompt restrictions.{0,100}mechanical guarantee",
        )

    def test_release_surfaces_describe_the_same_eight_skill_version(self) -> None:
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

        self.assertEqual("0.0.10", codex["version"])
        self.assertEqual(codex["version"], claude["version"])
        self.assertEqual(8, len(skill_names))
        self.assertIn("parallel-repository-research", skill_names)
        for public_description in (
            codex["description"],
            codex["interface"]["longDescription"],
            claude["description"],
            marketplace_steward["description"],
            root_readme,
            self.readme,
        ):
            self.assertIn("八", public_description)
        self.assertIn("并行只读", codex["interface"]["longDescription"])

        routing_paragraph = next(
            paragraph
            for paragraph in self.readme.split("\n\n")
            if "隐式" in paragraph and "write-agent-guides" in paragraph
        )
        self.assertIn("parallel-repository-research", routing_paragraph)
        self.assertRegex(routing_paragraph, r"其余六个.*显式|六个.*显式")


if __name__ == "__main__":
    unittest.main()
