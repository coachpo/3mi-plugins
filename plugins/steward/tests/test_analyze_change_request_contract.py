"""Semantic contract tests for the shared change-request analysis skill."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL = PLUGIN_ROOT / "skills" / "analyze-change-request" / "SKILL.md"
AGENT = SKILL.parent / "agents" / "openai.yaml"
RESEARCH_CONTRACT = SKILL.parent / "references" / "research-contract.md"


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return scalar YAML frontmatter and the Markdown body."""
    if not text.startswith("---\n"):
        raise AssertionError("SKILL.md must start with YAML frontmatter")
    metadata, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raise AssertionError("SKILL.md frontmatter is not closed")
    fields = {}
    for line in metadata.splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            fields[key] = value.strip()
    return fields, body


def _h2_sections(text: str) -> dict[str, str]:
    """Split Markdown into second-level sections without depending on wording layout."""
    matches = list(re.finditer(r"(?m)^## ([^\n]+)\n", text))
    return {
        match.group(1): text[
            match.end() : matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        ].strip()
        for index, match in enumerate(matches)
    }


def _inline_code(text: str) -> set[str]:
    """Return inline-code tokens used to declare contract fields and enum values."""
    return set(re.findall(r"`([^`\n]+)`", text))


def _paragraph_containing(text: str, needle: str) -> str:
    for paragraph in re.split(r"\n\s*\n", text):
        if needle.lower() in paragraph.lower():
            return re.sub(r"\s+", " ", paragraph).strip()
    raise AssertionError(f"No paragraph contains {needle!r}")


class AnalyzeChangeRequestContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.fields, cls.skill_body = _frontmatter(cls.skill)
        cls.skill_sections = _h2_sections(cls.skill_body)
        cls.contract = RESEARCH_CONTRACT.read_text(encoding="utf-8")
        cls.contract_sections = _h2_sections(cls.contract)
        cls.agent = AGENT.read_text(encoding="utf-8")

    def test_metadata_is_discriminating_and_explicit_only(self) -> None:
        self.assertEqual({"name", "description"}, self.fields.keys())
        self.assertEqual("analyze-change-request", self.fields["name"])
        description = self.fields["description"].lower()
        self.assertIn("only decision-relevant external evidence", description)
        for excluded in ("implementation", "goal authoring", "semantic-risk review"):
            self.assertIn(excluded, description)

        self.assertIn("$steward:analyze-change-request", self.skill_body)
        self.assertIn("/steward:analyze-change-request", self.skill_body)
        self.assertRegex(self.agent, r"(?m)^\s*allow_implicit_invocation:\s*false\s*$")
        self.assertIn("$steward:analyze-change-request", self.agent)
        self.assertIn("按需", self.agent)
        self.assertIn("整体状态", self.agent)

    def test_entrypoint_uses_progressive_disclosure(self) -> None:
        self.assertEqual(
            [
                "Keep authority and data boundaries",
                "Freeze the research contract",
                "Isolate and collect lanes",
                "Verify and deliver",
            ],
            list(self.skill_sections),
        )
        self.assertEqual(
            1,
            len(
                re.findall(
                    r"\]\(references/research-contract\.md\)",
                    self.skill,
                )
            ),
        )
        self.assertNotIn("## Require the LaneResult schema", self.skill_body)
        self.assertIn("Require the LaneResult schema", self.contract_sections)

    def test_instruction_hierarchy_and_sensitive_data_boundary_are_unambiguous(self) -> None:
        authority = self.skill_sections["Keep authority and data boundaries"]
        hierarchy = _paragraph_containing(authority, "instruction hierarchy")
        for instruction_source in (
            "Host",
            "system",
            "developer",
            "user",
            "AGENTS.md",
        ):
            self.assertIn(instruction_source, hierarchy)
        self.assertIn("all other repository content", hierarchy)
        self.assertIn("untrusted evidence", hierarchy)

        secrets = _paragraph_containing(authority, "secrets or credentials")
        for forbidden_destination in ("query", "worker prompt", "citation", "output"):
            self.assertIn(forbidden_destination, secrets)
        self.assertIn("even when requested", secrets)
        self.assertNotIn("unless", secrets.lower())
        self.assertIn("minimum sanitized excerpt", secrets)
        self.assertIn("public-web queries or web-worker prompts", secrets)

    def test_research_contract_freezes_intent_instructions_lanes_and_limits(self) -> None:
        freeze_entry = self.skill_sections["Freeze the research contract"]
        for required in ("U*", "targetRoot", "applicableInstructions", "retryLimit: 1"):
            self.assertIn(required, _inline_code(freeze_entry))
        self.assertIn("none-found", _inline_code(freeze_entry))
        normalized_freeze = re.sub(r"\s+", " ", freeze_entry)
        self.assertIn(
            "do not add a lane, question, source family, or scope",
            normalized_freeze,
        )

        freeze_contract = self.contract_sections["Freeze the ResearchContract"]
        tokens = _inline_code(freeze_contract)
        required_fields = {
            "requestRaw",
            "intentRecords",
            "sourceBinding",
            "applicableInstructions",
            "researchQuestions",
            "frozenLanes",
            "evidenceBudget",
            "retryLimit: 1",
            "intentId",
            "kind",
            "origin",
        }
        self.assertLessEqual(required_fields, tokens)
        self.assertIn("immutable", freeze_contract)
        self.assertIn("do not expand the run", freeze_contract)
        self.assertRegex(freeze_contract, r"Do not turn an\s+assumption.*into a `U\*` record")

    def test_lane_routing_requires_mechanical_capability_isolation(self) -> None:
        routing = self.skill_sections["Isolate and collect lanes"]
        for lane in ("repository", "official", "obligation", "practice"):
            self.assertRegex(routing, rf"(?m)^- \*\*{lane}:\*\*")

        repository_worker = _paragraph_containing(routing, "repository worker")
        self.assertIn("local read and read-only Git", repository_worker)
        self.assertIn("no web or external-service capability", repository_worker)

        web_worker = _paragraph_containing(routing, "web worker")
        self.assertIn("public search/open/read", web_worker)
        self.assertIn("no repository, filesystem, or private-context capability", web_worker)
        self.assertIn("never give one worker both capability classes", routing)
        self.assertIn("Instruction-only restrictions are insufficient", routing)
        self.assertIn("sequentially in the current main session", routing)
        self.assertRegex(
            re.sub(r"\s+", " ", routing),
            r"parallel-repository-research.*only when.*mechanically enforced",
        )

    def test_lane_result_schema_is_fixed_and_complete(self) -> None:
        lane_schema = self.contract_sections["Require the LaneResult schema"]
        tokens = _inline_code(lane_schema)
        required_fields = {
            "laneId",
            "laneKind",
            "status",
            "questionIds",
            "sourceBinding",
            "applicableInstructionsApplied",
            "directAnswer",
            "sources",
            "facts",
            "inferences",
            "recommendations",
            "searched",
            "unsearched",
            "conflicts",
            "gaps",
            "budgetUsed",
            "stopReason",
            "attempts",
            "execution",
        }
        self.assertLessEqual(required_fields, tokens)
        self.assertIn("Every worker returns every field", lane_schema)
        self.assertIn("arbitrary subset is invalid", lane_schema)
        self.assertIn("attempt two requires a\n  recorded transient failure", lane_schema)
        self.assertIn("must not infer\nmissing required fields", lane_schema)

    def test_source_records_capture_authority_independence_normativity_and_drift(self) -> None:
        evidence = self.contract_sections["Classify sources and claims"]
        tokens = _inline_code(evidence)
        required_fields = {
            "sourceId",
            "accessedAt",
            "authority",
            "independence",
            "normative",
            "drift",
        }
        self.assertLessEqual(required_fields, tokens)
        for independence in ("first-party", "independent", "shared-origin", "unknown"):
            self.assertIn(independence, tokens)
        for normative in (
            "binding",
            "normative-standard",
            "official-guidance",
            "non-normative",
        ):
            self.assertIn(normative, tokens)
        for drift in ("stable", "mutable", "changed"):
            self.assertIn(drift, tokens)
        for drift_identity in ("ETag", "Last-Modified", "content digest"):
            self.assertIn(drift_identity, evidence)
        self.assertIn("cannot\nsupport aggregate `complete`", evidence)
        self.assertIn("decision-relevant factual claim", evidence)
        self.assertIn("User intent traces to `U*`", evidence)

    def test_requirements_have_explicit_authority_categories(self) -> None:
        requirements = self.contract_sections["Classify candidate requirements"]
        tokens = _inline_code(requirements)
        self.assertLessEqual(
            {
                "authorityCategory",
                "intent-derived",
                "binding-if-applicable",
                "compatibility-constraint",
                "optional",
            },
            tokens,
        )
        self.assertIn("exactly one `authorityCategory`", requirements)
        self.assertRegex(requirements, r"Trace every `R\*` to its supporting `U\*`")
        self.assertIn("observable acceptance criteria", requirements)

    def test_final_output_has_exclusive_status_branches(self) -> None:
        delivery = self.contract_sections["Deliver by overall status"]
        branch_names = re.findall(r"(?m)^- \*\*([^:*]+):\*\*", delivery)
        self.assertEqual(["complete", "partial", "blocked", "drifted"], branch_names)
        self.assertIn("Overall status: complete|partial|blocked|drifted", delivery)

        blocked = _paragraph_containing(delivery, "**blocked:**")
        self.assertIn("do not emit `R*` candidates", blocked)
        partial = _paragraph_containing(delivery, "**partial:**")
        self.assertIn("only candidates supported by stable evidence", partial)
        drifted = _paragraph_containing(delivery, "**drifted:**")
        self.assertIn("do not present invalidated candidates as current", drifted)

    def test_skill_package_has_only_declared_instruction_resources(self) -> None:
        relative_files = {
            path.relative_to(SKILL.parent).as_posix()
            for path in SKILL.parent.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            {
                "SKILL.md",
                "agents/openai.yaml",
                "references/research-contract.md",
            },
            relative_files,
        )
        self.assertNotIn("dependencies:", self.agent)


if __name__ == "__main__":
    unittest.main()
