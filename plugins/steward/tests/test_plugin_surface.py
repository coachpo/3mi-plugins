from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
EXPECTED_SKILLS = {
    "configure-project-verification",
    "draft-consensus-goal",
    "review-semantic-risks",
    "run-closed-loop-verification",
    "run-engineering-control-loop",
    "write-agent-guides",
    "write-project-docs",
}
FORBIDDEN_HOST_GOAL_TOKENS = (
    "get_goal",
    "create_goal",
    "update_goal",
    "token_budget",
)


class PluginSurfaceTests(unittest.TestCase):
    def test_readme_manifest_and_skill_directories_agree(self) -> None:
        skill_root = PLUGIN_ROOT / "skills"
        actual = {
            path.name
            for path in skill_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        }
        self.assertEqual(EXPECTED_SKILLS, actual)

        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("插件包含七个共享技能", readme)
        self.assertIn("codex plugin marketplace add coachpo/plugins-codex --ref main", readme)
        self.assertIn("codex plugin add steward@coachpo", readme)
        self.assertIn("claude plugin marketplace add coachpo/plugins-codex@main", readme)
        self.assertIn("claude plugin install steward@coachpo", readme)
        self.assertIn("| 技能 | 使用时机 | 读写模式 | 主要结果 |", readme)
        self.assertIn(
            "除 `write-agent-guides` 保留默认的隐式路由能力外，其余六个技能",
            readme,
        )
        self.assertIn(
            "显式调用 `run-engineering-control-loop` 会授权其启动前披露并冻结",
            readme,
        )
        self.assertIn("bootstrap/execute/export/aggregate 写各操作启动前冻结的项目内路径", readme)
        self.assertIn("turnkey configure 固定生成 GitHub Actions workflow", readme)
        for skill in EXPECTED_SKILLS:
            self.assertEqual(
                1,
                readme.count(f"](skills/{skill}/SKILL.md)"),
                msg=f"README skill link mismatch for {skill}",
            )
            skill_text = (skill_root / skill / "SKILL.md").read_text(
                encoding="utf-8"
            )
            self.assertRegex(skill_text, rf"(?m)^name: {re.escape(skill)}$")
            agent_text = (skill_root / skill / "agents" / "openai.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn(f"$steward:{skill}", agent_text)
            if skill == "write-agent-guides":
                self.assertNotIn("allow_implicit_invocation: false", agent_text)
            else:
                self.assertIn("allow_implicit_invocation: false", agent_text)

        codex_manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        claude_manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("steward", PLUGIN_ROOT.name)
        for manifest in (codex_manifest, claude_manifest):
            self.assertEqual("steward", manifest["name"])
            self.assertEqual("0.0.3", manifest["version"])
            self.assertEqual("./skills/", manifest["skills"])
        self.assertEqual("Steward", codex_manifest["interface"]["displayName"])
        self.assertEqual("Steward", claude_manifest["displayName"])
        self.assertIn("七技能", codex_manifest["interface"]["longDescription"])
        prompts = codex_manifest["interface"]["defaultPrompt"]
        self.assertGreaterEqual(len(prompts), 1)
        self.assertLessEqual(len(prompts), 3)
        for prompt in prompts:
            self.assertLessEqual(len(prompt), 128)
        prompt_text = "\n".join(prompts)
        referenced = set(re.findall(r"\$steward:([a-z0-9-]+)", prompt_text))
        self.assertTrue(referenced)
        self.assertLessEqual(referenced, actual)
        self.assertIn("draft-consensus-goal", referenced)
        self.assertIn("configure-project-verification", referenced)
        self.assertIn("run-engineering-control-loop", referenced)
        self.assertIn("已验证的七行 GOAL", prompts[0])
        self.assertIn("仅在超长或明确要求时创建交接文档", prompts[0])

    def test_contract_index_and_packaged_license_are_resolvable(self) -> None:
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("](references/control-plane-contracts.md)", readme)
        self.assertIn("[MIT](LICENSE)", readme)
        self.assertTrue((PLUGIN_ROOT / "LICENSE").is_file())

        contract_index = (
            PLUGIN_ROOT / "references" / "control-plane-contracts.md"
        ).read_text(encoding="utf-8")
        for name in (
            "goal_contract.py",
            "architecture_profiles.py",
            "invariant_contract.py",
            "semantic_review.py",
            "project_verification.py",
            "verification_pipeline.py",
            "verification-profile-v1.schema.json",
            "impact-plan-v1.schema.json",
            "ci-plan-v1.schema.json",
            "platform-evidence-v1.schema.json",
            "platform-evidence-aggregation-v1.schema.json",
            "run-closed-loop-verification",
        ):
            self.assertIn(name, contract_index)

        self.assertEqual(
            (REPO_ROOT / "LICENSE").read_bytes(),
            (PLUGIN_ROOT / "LICENSE").read_bytes(),
        )

    def test_skill_entrypoints_are_lean_and_progressively_disclosed(self) -> None:
        descriptions: set[str] = set()
        forbidden_global_policy = (
            "Before the first tool call",
            "first tool call",
            "首次工具调用前",
            "首个工具调用前",
            "Update again only",
        )
        for skill in EXPECTED_SKILLS:
            path = PLUGIN_ROOT / "skills" / skill / "SKILL.md"
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            self.assertLessEqual(len(raw), 8_000, msg=f"entrypoint too large: {skill}")
            match = re.search(r"(?m)^description:\s*(.+)$", text)
            self.assertIsNotNone(match, msg=skill)
            description = match.group(1).strip().strip('"')
            self.assertLessEqual(len(description), 480, msg=f"description too long: {skill}")
            self.assertNotIn(description, descriptions, msg=f"duplicate description: {skill}")
            descriptions.add(description)
            for token in forbidden_global_policy:
                self.assertNotIn(token, text, msg=f"global policy leaked into {skill}")
            for token in FORBIDDEN_HOST_GOAL_TOKENS:
                self.assertNotIn(token, text, msg=f"host Goal API leaked into {skill}")
            if skill != "write-agent-guides":
                self.assertIn(
                    "This workflow requires an explicit",
                    text,
                    msg=f"explicit invocation guard missing from {skill}",
                )

        orchestrator = (
            PLUGIN_ROOT / "skills" / "run-engineering-control-loop" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("request-view --target-kind", orchestrator)
        self.assertIn("strict-handoff", orchestrator)

        closed_loop = (
            PLUGIN_ROOT / "skills" / "run-closed-loop-verification" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("project-adapter.md", closed_loop)
        self.assertIn("state-and-evidence.md", closed_loop)
        self.assertIn("platform-evidence.md", closed_loop)

        project_docs = (
            PLUGIN_ROOT / "skills" / "write-project-docs" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("fsync", project_docs)
        self.assertNotIn("inode", project_docs)

    def test_non_template_relative_markdown_links_resolve_inside_plugin(self) -> None:
        markdown_paths = [PLUGIN_ROOT / "README.md"]
        markdown_paths.extend((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))
        markdown_paths.extend((PLUGIN_ROOT / "references").rglob("*.md"))
        markdown_paths.extend((PLUGIN_ROOT / "skills").glob("*/references/*.md"))
        link_re = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
        root = PLUGIN_ROOT.resolve()
        for source in markdown_paths:
            text = source.read_text(encoding="utf-8")
            for raw_target in link_re.findall(text):
                target = raw_target.strip().strip("<>")
                if (
                    not target
                    or target.startswith(("#", "https://", "http://", "mailto:"))
                    or any(token in target for token in ("{{", "}}", "<", ">"))
                ):
                    continue
                target = unquote(target.split("#", 1)[0])
                resolved = (source.parent / target).resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    self.fail(f"link escapes plugin: {source}: {raw_target}")
                self.assertTrue(
                    resolved.exists(), msg=f"broken link: {source}: {raw_target}"
                )

    def test_profile_inventory_and_python_overlays_are_exact(self) -> None:
        profile_root = PLUGIN_ROOT / "references" / "architecture-profiles"
        catalog = json.loads((profile_root / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(1, catalog["schemaVersion"])
        self.assertFalse((profile_root / "sources.lock.json").exists())
        profiles = {entry["id"]: entry for entry in catalog["profiles"]}
        self.assertEqual(
            {
                "android",
                "cloudflare-workers",
                "django",
                "fastapi",
                "golang",
                "python",
                "tauri-2",
            },
            set(profiles),
        )
        self.assertEqual(["python"], profiles["django"]["extends"])
        self.assertEqual(["python"], profiles["fastapi"]["extends"])
        self.assertEqual([], profiles["python"]["extends"])
        for entry in catalog["profiles"]:
            profile_path = profile_root / entry["path"]
            self.assertTrue(profile_path.is_file())
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(1, profile["schemaVersion"])
            self.assertEqual("1.0.0", profile["profileVersion"])
            self.assertNotIn("source", profile)
            for collection in ("invariants", "checks", "scenarios"):
                for item in profile[collection]:
                    self.assertNotIn("sourceRefs", item)
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("3mi" + "-harness", readme)
        for profile_id in profiles:
            self.assertIn(f"`{profile_id}`", readme)
        self.assertIn("Django 与 FastAPI 是 Python overlay", readme)
        self.assertIn("applicabilityByScope.state = unverified", readme)
        self.assertIn("未列出的 capability 不会补写进 selection artifact", readme)
        self.assertIn("当前 validator 只校验 token 形状与三态值", readme)
        self.assertIn("selection handoff 同时绑定 `catalogDigest` 与 `contentDigest`", readme)
        self.assertIn("persisted compiled JSON 不是权威", readme)
        self.assertIn("以下命令从插件根目录运行", readme)
        self.assertIn("均从 schema v1 起步", readme)
        self.assertNotIn("Architecture profiles v2 迁移", readme)
        self.assertNotIn("INV-CFSAAS", readme)
        self.assertIn("campaign_platform_projection", readme)
        self.assertIn(
            "其他 target 与 host 不同的 cross-target 情况不会由该 helper 保留 target identity",
            readme,
        )
        self.assertIn("极深但仍可解析的输入可能触发未捕获的递归错误", readme)
        self.assertIn("profile package 不依赖外部标准仓库", readme)

    def test_packaged_sources_do_not_embed_development_machine_paths(self) -> None:
        text_suffixes = {".json", ".md", ".py", ".txt", ".yaml", ".yml"}
        forbidden_tokens = (
            "/Users/" + "qingli",
            "plugins/steward/" + "scripts/goal_contract.py",
            "<plugin-" + "root>",
        )
        for path in PLUGIN_ROOT.rglob("*"):
            self.assertFalse(path.is_symlink(), msg=str(path.relative_to(PLUGIN_ROOT)))
            if not path.is_file() or path.suffix not in text_suffixes:
                continue
            text = path.read_text(encoding="utf-8")
            for forbidden in forbidden_tokens:
                self.assertNotIn(
                    forbidden,
                    text,
                    msg=str(path.relative_to(PLUGIN_ROOT)),
                )

    def test_root_readme_and_marketplaces_publish_the_same_plugin(self) -> None:
        root_readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("[`steward`](plugins/steward/README.md)", root_readme)
        self.assertIn(
            "codex plugin marketplace add coachpo/plugins-codex --ref main",
            root_readme,
        )
        self.assertIn("codex plugin add steward@coachpo", root_readme)
        self.assertIn(
            "claude plugin marketplace add coachpo/plugins-codex@main",
            root_readme,
        )
        self.assertIn("claude plugin install steward@coachpo", root_readme)
        self.assertIn("$steward:<skill-name>", root_readme)
        self.assertIn("/steward:<skill-name>", root_readme)

        codex_marketplace = json.loads(
            (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        claude_marketplace = json.loads(
            (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("coachpo", codex_marketplace["name"])
        self.assertEqual("coachpo", claude_marketplace["name"])
        codex_entries = {
            entry["name"]: entry for entry in codex_marketplace["plugins"]
        }
        claude_entries = {
            entry["name"]: entry for entry in claude_marketplace["plugins"]
        }
        self.assertEqual({"steward"}, set(codex_entries))
        self.assertEqual({"steward"}, set(claude_entries))
        self.assertEqual(
            "./plugins/steward",
            codex_entries["steward"]["source"]["path"],
        )
        self.assertEqual(
            codex_entries["steward"]["source"]["path"],
            claude_entries["steward"]["source"],
        )

    def test_orchestrator_exposes_profiles_and_canonical_handoffs(self) -> None:
        skill = (
            PLUGIN_ROOT / "skills" / "run-engineering-control-loop" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("architecture_profiles.py validate", skill)
        self.assertIn("`select`, and `compile`", skill)
        self.assertIn("project-local controls beneath `.steward/`", skill)
        self.assertIn("Resolve, freeze, and disclose the exact write set", skill)
        self.assertIn("| Adapter and source |", skill)
        self.assertIn("| Semantic review |", skill)
        self.assertIn("| Trace binding |", skill)
        self.assertLess(skill.index("| Adapter and source |"), skill.index("| Semantic review |"))
        self.assertLess(skill.index("| Semantic review |"), skill.index("| Trace binding |"))
        self.assertIn("The coordinator owns source policy, request/Review paths", skill)
        self.assertIn("The Reviewer never selects paths", skill)
        self.assertNotIn("request-view --target-kind", skill)

        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        for trace in (
            "`C* → case`",
            "`INV-* → case`",
            "`RF-* → 反例 case`",
            "`fix → violated invariant → permanent guardrail`",
        ):
            self.assertIn(trace, readme)
        self.assertIn("audit 只证明声明范围内的证据闭环，不冒充语义真值", readme)
        self.assertIn("## 机器契约与追踪", readme)
        self.assertIn("## 执行、恢复与完成", readme)
        self.assertIn("从第一个缺失或失效的 gate 继续", readme)
        self.assertIn("不能只刷新 digest/fingerprint", readme)
        self.assertIn("项目原生 quick", readme)
        self.assertIn("可选 kernel quick / ordinary initial full", readme)
        self.assertIn("按失败阶段续跑 / ordinary initial gate", readme)
        self.assertIn("重新派生 profile selection evidence", readme)
        self.assertIn("select → compile → canonical INV mapping → AGENTS router", readme)
        self.assertIn("ordinary initial gate", readme)
        self.assertIn("phase-specific continuation", readme)
        self.assertIn("quick failure 重跑完整 quick", readme)
        self.assertIn("initial failure 从 checkpoint 续跑", readme)
        self.assertIn("regression failure 直接回到 `READY_FOR_REGRESSION`", readme)
        self.assertIn("任何 regression source drift 都只保存一次 `INVALIDATED`", readme)
        self.assertIn("`quick` 或 `RETEST_PASSED` 均不能替代最终完整回归", readme)
        self.assertIn("same-source full regression", readme)
        self.assertIn("完成前必须重新校验 `.steward/goal.txt`", readme)
        self.assertIn(
            "canonical digest 与 adapter、campaign trace input 一致",
            readme,
        )
        self.assertIn("post-fix Review 还必须保留初始化时的 `RF-*` ID", readme)
        self.assertIn("diff-target 允许新的 head identity", readme)
        self.assertIn(
            "coordinator 在 Review 前调用只读 `semantic_review.py request-view`",
            readme,
        )
        self.assertIn(
            "expected-request 与 Review handoff 使用两个不同的精确项目相对路径",
            readme,
        )
        self.assertIn("Reviewer 只通过 `--expected-review-request` 消费前者", readme)
        self.assertIn("固定为 adapter 的 `traceability.reviewFindings.reviewRequestSha256`", readme)
        self.assertIn("平台 evidence 可独立导出/聚合", readme)
        self.assertIn("standalone 模式交付有证据的 prose findings/gaps", readme)
        self.assertIn("`legacy` 不只表示 unattested", readme)
        self.assertIn("binding 完整时输出 machine-attested canonical view", readme)
        self.assertIn("RequestedCoverageSatisfied<br/>∧ audit.ok", readme)
        self.assertIn("当前没有一个跨合同 verifier 自动合并这两条证据腿", readme)
        self.assertIn("schema 1 standalone journal 不受支持", readme)
        self.assertIn("bundle 自哈希不是远程证明", readme)
        self.assertIn("architecture selection 的 `catalogDigest` 与 verification 的", readme)
        self.assertIn("`bundleFingerprint`", readme)
        self.assertIn("optional platform 可以额外出现", readme)
        self.assertIn("Git top-level 就是 profile 的 `projectRoot`", readme)
        self.assertIn("始终保留独立的 selector self-test entry", readme)
        self.assertIn("公开 renderer API 的写模式都 fail-stop", readme)
        self.assertIn("任何非空 env override 都可以是绝对路径或相对项目根的路径", readme)
        self.assertIn("实际 env-bound runtime 和 remote variable 都要报告为未验证", readme)
        self.assertIn("直接聚合仍要求目标 `projectRoot` 为当前目录", readme)
        self.assertIn("突然断电时的目录项持久性保证弱于 POSIX directory `fsync`", readme)
        self.assertIn("`resume` 可以启动 fresh `PENDING` campaign", readme)
        self.assertIn(
            "新的 strict Review 由 coordinator 调用只读 `request-view` 冻结 canonical expected request",
            readme,
        )
        self.assertIn("`draft-consensus-goal` 是唯一 GOAL 作者", readme)
        self.assertIn(
            "`run-engineering-control-loop` 以 `.steward/goal.txt` 与有效 handoff/campaign journal 恢复",
            readme,
        )
        self.assertIn(
            "宿主对话、任务或 continuation state 不作为恢复或完成权威",
            readme,
        )
        self.assertIn("冻结的写集内保存 profile selection", readme)
        self.assertIn("原工程请求已经明确授权的初始源码改动", readme)

    def test_project_verification_surface_matches_runtime_contracts(self) -> None:
        commands = {
            "validate-profile",
            "plan-impact",
            "validate-impact",
            "build-ci-plan",
            "validate-ci-plan",
            "render-adapter",
            "render-local",
            "render-github",
            "review",
            "configure",
        }
        cli = (PLUGIN_ROOT / "scripts" / "project_verification.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            commands,
            set(re.findall(r'add_parser\("([a-z-]+)"\)', cli)),
        )

        contracts = PLUGIN_ROOT / "references" / "project-verification"
        profile = json.loads(
            (contracts / "verification-profile-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        for derived in (
            "profileFingerprint",
            "verificationCatalogFingerprint",
            "adapterCaseIds",
            "normalizedProfile",
        ):
            self.assertNotIn(derived, profile["properties"])
            self.assertIn(derived, cli)
        self.assertIn(
            "steward.verification-profile-validation", cli
        )
        self.assertEqual(
            {"pluginRoot", "pythonExecutables"},
            set(profile["properties"]["runtime"]["required"]),
        )
        self.assertEqual(
            {
                "profile",
                "impactPlan",
                "ciPlan",
                "localEntry",
                "workflow",
                "derivedAdapters",
                "campaigns",
                "evidenceBundles",
                "aggregation",
            },
            set(profile["properties"]["outputs"]["required"]),
        )
        ci_plan = json.loads(
            (contracts / "ci-plan-v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            64,
            ci_plan["$defs"]["entry"]["properties"]["shardCount"][
                "maximum"
            ],
        )
        for name in (
            "platform-evidence-v1.schema.json",
            "platform-evidence-aggregation-v1.schema.json",
        ):
            schema = json.loads((contracts / name).read_text(encoding="utf-8"))
            self.assertEqual(
                {"darwin", "linux", "windows"},
                set(schema["$defs"]["platform"]["enum"]),
            )

        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        for token in (
            "`changes → impact plan → local quick`",
            "`CI commit → full shard → shard audit → platform evidence bundle → aggregation`",
            "STEWARD_PLUGIN_ROOT",
            "真实远程 GitHub Actions",
            "不会**跨 shard 重放全局 `C*`、`INV-*`、`RF-*`",
            "`evidenceBundles/<entryId>.json`",
            "聚合只能写到 `outputs.aggregation`",
            "`ubuntu-24.04`、`macos-15`、`windows-2025`",
            "不调度独立的全局 trace campaign",
        ):
            self.assertIn(token, readme)

        closed_loop_commands = {
            "validate-adapter",
            "init",
            "status",
            "observe-source",
            "run",
            "resume",
            "record-fix",
            "record-review",
            "supersede-fix",
            "retest",
            "audit",
            "export-platform-evidence",
            "aggregate-platform-evidence",
        }
        command_sentence = re.search(r"命令集合仍为 ([^。]+)。", readme)
        self.assertIsNotNone(command_sentence)
        self.assertEqual(
            closed_loop_commands,
            set(re.findall(r"`([a-z-]+)`", command_sentence.group(1))),
        )
        campaign_cli = (
            PLUGIN_ROOT
            / "skills"
            / "run-closed-loop-verification"
            / "scripts"
            / "cli.py"
        ).read_text(encoding="utf-8")
        loop = re.search(
            r"for name in \(\s*(.*?)\s*\):\s*\n\s*sub = subparsers\.add_parser",
            campaign_cli,
            re.DOTALL,
        )
        self.assertIsNotNone(loop)
        runtime_commands = set(re.findall(r'"([a-z-]+)"', loop.group(1)))
        runtime_commands.update(
            re.findall(r'subparsers\.add_parser\("([a-z-]+)"\)', campaign_cli)
        )
        self.assertEqual(closed_loop_commands, runtime_commands)

        contract_index = (
            PLUGIN_ROOT / "references" / "control-plane-contracts.md"
        ).read_text(encoding="utf-8")
        self.assertIn("ten\npublic subcommands", contract_index)
        self.assertIn("does **not** replay global", contract_index)
        self.assertIn(
            "Neither `aggregation.ok` nor `audit.ok` is semantic truth",
            contract_index,
        )
        self.assertIn(
            "No schema-4 campaign automatically restarts an\n"
            "invalidated regression",
            contract_index,
        )

    def test_official_guidance_lifecycle_contracts_are_explicit(self) -> None:
        skills = PLUGIN_ROOT / "skills"
        agent_guides = (skills / "write-agent-guides" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        project_docs = (skills / "write-project-docs" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        orchestrator = (
            skills / "run-engineering-control-loop" / "SKILL.md"
        ).read_text(encoding="utf-8")
        closed_loop = (
            skills / "run-closed-loop-verification" / "SKILL.md"
        ).read_text(encoding="utf-8")
        semantic = (skills / "review-semantic-risks" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        configure = (
            skills / "configure-project-verification" / "SKILL.md"
        ).read_text(encoding="utf-8")
        draft_goal = (
            skills / "draft-consensus-goal" / "SKILL.md"
        ).read_text(encoding="utf-8")

        agent_guides += "\n" + (
            skills / "write-agent-guides" / "scripts" / "validate_engineering_router.py"
        ).read_text(encoding="utf-8")
        project_docs += "\n" + (
            skills / "write-project-docs" / "references" / "document-rules.md"
        ).read_text(encoding="utf-8")
        project_docs += "\n" + (
            skills / "write-project-docs" / "references" / "iteration-strategy.md"
        ).read_text(encoding="utf-8")
        configure += "\n" + (
            skills
            / "configure-project-verification"
            / "references"
            / "configuration-contract.md"
        ).read_text(encoding="utf-8")
        goal_authoring = (PLUGIN_ROOT / "references" / "goal-authoring.md").read_text(
            encoding="utf-8"
        )
        orchestrator += "\n" + (
            skills / "review-semantic-risks" / "references" / "strict-handoff.md"
        ).read_text(encoding="utf-8")
        orchestrator += "\n" + (
            skills
            / "run-closed-loop-verification"
            / "references"
            / "state-and-evidence.md"
        ).read_text(encoding="utf-8")
        closed_loop += "\n" + (
            skills
            / "run-closed-loop-verification"
            / "references"
            / "state-and-evidence.md"
        ).read_text(encoding="utf-8")
        closed_loop += "\n" + (
            skills
            / "run-closed-loop-verification"
            / "references"
            / "project-adapter.md"
        ).read_text(encoding="utf-8")
        semantic += "\n" + (
            skills / "review-semantic-risks" / "references" / "strict-handoff.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Review, explanation, diagnosis, report, and planning requests are read-only", agent_guides)
        self.assertIn("Root write permission is required only when the root file itself must change", agent_guides)
        self.assertIn("validate_engineering_router.py", agent_guides)
        self.assertIn("python3 -B", agent_guides)
        self.assertIn("Never infer Simplified Chinese from a CJK percentage", agent_guides)
        self.assertIn("`AGENTS.md` is the only instruction authority", agent_guides)
        self.assertIn("same-directory `CLAUDE.md`", agent_guides)
        self.assertIn("@AGENTS.md", agent_guides)
        self.assertIn("a symlink\nto that same-directory `AGENTS.md`", agent_guides)
        self.assertIn("Treat substantive content in an existing `CLAUDE.md`", agent_guides)
        self.assertIn("merge still-valid rules", agent_guides)
        self.assertIn("A focused request changes only the affected documents", project_docs)
        self.assertIn("do not hand-edit those regions or copy their implementation", project_docs)
        self.assertIn("iteration-strategy.md", project_docs)
        self.assertIn("MVP", project_docs)
        self.assertIn("update_iteration_strategy.py", project_docs)
        self.assertIn("unsupported language", project_docs)
        self.assertIn("validate_project_docs.py", project_docs)
        self.assertIn("`--strict` 下升级为失败", project_docs)
        self.assertIn("规范桥接是完整内容仅含 `@AGENTS.md`", project_docs)
        self.assertIn("指向同目录 `AGENTS.md` 的符号链接", project_docs)
        self.assertIn("本技能不自动覆盖 `CLAUDE.md`", project_docs)

        self.assertIn("project_verification.py", configure)
        self.assertIn("`validate-ci-plan`", configure)
        self.assertIn("Static projection writes occur only through `configure --allow-write`", configure)
        self.assertIn("Observable", configure)
        self.assertIn("drift fails closed", configure)
        self.assertIn("The lock coordinates only writers using the same protocol", configure)
        self.assertIn("The base adapter is the sole case catalog", configure)
        self.assertIn("Aggregation proves the declared", configure)
        self.assertIn("entry/case/platform", configure)
        self.assertIn("Consume a GOAL only when", configure)
        self.assertIn("user explicitly supplies its seven-line text or path", configure)
        self.assertIn("never discover, query, create", configure)
        self.assertIn("update, or report host Goal state", configure)

        self.assertIn("goal-authoring.md", draft_goal)
        self.assertIn("only Steward skill that authors a GOAL", draft_goal)
        self.assertIn("`draft-consensus-goal` is its sole skill owner", goal_authoring)
        self.assertIn("The strategy is an execution default, not user consensus", goal_authoring)
        self.assertIn("only when the user accepted that item", goal_authoring)
        self.assertIn("Never derive the strategy from the MVP switch", goal_authoring)
        self.assertIn("same failure repeats", goal_authoring)

        self.assertIn("first incomplete or invalid gate", orchestrator)
        self.assertIn("Re-derive architecture-profile evidence", orchestrator)
        self.assertIn("Current Iteration Strategy", orchestrator)
        self.assertIn("| Adapter and source |", orchestrator)
        self.assertIn("| Semantic review |", orchestrator)
        self.assertIn("| Trace binding |", orchestrator)
        self.assertIn("The coordinator owns source policy", orchestrator)
        self.assertIn("The Reviewer never selects paths", orchestrator)
        self.assertIn("persist the canonical\nobjective exactly", orchestrator)
        self.assertIn("`.steward/goal.txt`", orchestrator)
        self.assertIn("campaign journal `status`", orchestrator)
        self.assertIn("only durable recovery authority", orchestrator)
        orchestrator_entry = (
            skills / "run-engineering-control-loop" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("request-view --target-kind", orchestrator_entry)
        self.assertIn("RequestedCoverageSatisfied ∧ audit.ok", orchestrator)

        self.assertIn("Choose the operation and reference", closed_loop)
        self.assertIn("journal `resumeMode`", closed_loop)
        self.assertIn("task-wide source-repair", closed_loop)
        self.assertIn("new root does not reset the budget", closed_loop)
        self.assertIn("RequestedCoverageSatisfied ∧ audit.ok", closed_loop)
        self.assertIn("pending_fix_superseded", closed_loop)
        self.assertIn("REVIEW_HANDOFF_REQUIRED", closed_loop)

        self.assertIn("`standalone`", semantic)
        self.assertIn("`strict-handoff`", semantic)
        self.assertIn("The coordinator alone owns", semantic)
        self.assertIn("request-view --target-kind source", semantic)
        self.assertIn("request-view --target-kind diff", semantic)
        self.assertIn("scopeVerified=true", semantic)
        self.assertIn("bindingsVerified=true", semantic)
        self.assertIn("Post-fix review", semantic)

        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("PATH 中可用的 `python3`", readme)

    def test_semantic_review_attestation_surface_matches_runtime(self) -> None:
        schema = json.loads(
            (PLUGIN_ROOT / "references" / "semantic-review-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("attestation", schema["required"])
        self.assertNotIn("reviewRequest", schema["required"])
        request_condition = next(
            item
            for item in schema["allOf"]
            if item.get("if") == {"required": ["reviewRequest"]}
        )
        self.assertEqual(["attestation"], request_condition["then"]["required"])
        request_bound_gap_items = request_condition["then"]["properties"][
            "attestation"
        ]["properties"]["gaps"]["items"]
        self.assertEqual(
            {"required": ["paths"]},
            request_bound_gap_items["then"],
        )
        self.assertEqual(
            {"target", "requestedPaths", "requestSha256"},
            set(schema["$defs"]["reviewRequest"]["required"]),
        )
        self.assertEqual(
            {
                "kind",
                "sourceFingerprint",
                "baseIdentity",
                "headIdentity",
            },
            set(schema["$defs"]["diffReviewTarget"]["required"]),
        )
        attestation = schema["$defs"]["attestation"]
        self.assertEqual(
            {
                "sourceFingerprint",
                "goalContractSha256",
                "invariantsSha256",
                "outcome",
                "scope",
                "gaps",
            },
            set(attestation["required"]),
        )
        self.assertEqual(
            {"findings", "no-findings", "incomplete"},
            set(attestation["properties"]["outcome"]["enum"]),
        )
        self.assertEqual(
            {
                "insufficient-evidence",
                "unreviewed-scope",
                "unavailable-context",
            },
            set(schema["$defs"]["reviewGap"]["properties"]["kind"]["enum"]),
        )
        self.assertIn("paths", schema["$defs"]["reviewGap"]["properties"])
        self.assertEqual(
            [
                {
                    "if": {
                        "required": ["kind"],
                        "properties": {"kind": {"const": "unreviewed-scope"}},
                    },
                    "else": {"properties": {"paths": False}},
                }
            ],
            schema["$defs"]["reviewGap"]["allOf"],
        )

        validator = (PLUGIN_ROOT / "scripts" / "semantic_review.py").read_text(
            encoding="utf-8"
        )
        commands = re.search(
            r'"command",\s*choices=\(([^)]+)\)', validator, re.DOTALL
        )
        self.assertIsNotNone(commands)
        self.assertEqual(
            {"check", "view", "digest", "case-candidates", "request-view"},
            set(re.findall(r'"([a-z-]+)"', commands.group(1))),
        )

        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        for token in (
            "record-fix → fresh read-only Review",
            "canonical `reviewRequest`",
            "只读 `request-view` 是 coordinator 的公共 canonical request 构造入口",
            "`scopeVerified=true` 与 `bindingsVerified=true`",
            "`traceability.reviewFindings.reviewRequestSha256`",
            "diff-target 允许新的 head identity",
            "schema 2/3 legacy journal 仅支持只读 `status`/`audit`",
            "legacy Review 输入包括 unattested 以及 attestation-only",
            "canonical `view`",
            "首次 `observe-source` 前必须先冻结 source inventory",
            "requested scope 未覆盖时不得输出完整 `no-findings`",
            "traceabilityMode = none|legacy|attested",
        ):
            self.assertIn(token, readme)

        review_agent = (
            PLUGIN_ROOT
            / "skills"
            / "review-semantic-risks"
            / "agents"
            / "openai.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("standalone 模式", review_agent)
        self.assertIn("strict-handoff", review_agent)
        self.assertIn("coordinator 已提供冻结 bindings", review_agent)

        orchestrator_agent = (
            PLUGIN_ROOT
            / "skills"
            / "run-engineering-control-loop"
            / "agents"
            / "openai.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("完整持久闭环", orchestrator_agent)
        self.assertIn("request-bound Review", orchestrator_agent)
        self.assertIn("同源完整回归和 audit", orchestrator_agent)

        closed_loop_agent = (
            PLUGIN_ROOT
            / "skills"
            / "run-closed-loop-verification"
            / "agents"
            / "openai.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("journal resumeMode", closed_loop_agent)
        self.assertIn("同源完整回归与 audit", closed_loop_agent)

        orchestrator = (
            PLUGIN_ROOT
            / "skills"
            / "run-engineering-control-loop"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Adapter and source", orchestrator)
        self.assertIn("Trace binding", orchestrator)
        self.assertLess(orchestrator.index("| Adapter and source |"), orchestrator.index("| Semantic review |"))
        self.assertLess(orchestrator.index("| Semantic review |"), orchestrator.index("| Trace binding |"))

        contract_index = (
            PLUGIN_ROOT / "references" / "control-plane-contracts.md"
        ).read_text(encoding="utf-8")
        self.assertIn("thirteen public commands", contract_index)
        self.assertIn("`pending_fix_superseded`", contract_index)

        closed_loop = (
            PLUGIN_ROOT
            / "skills"
            / "run-closed-loop-verification"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        state_contract = (
            PLUGIN_ROOT
            / "skills"
            / "run-closed-loop-verification"
            / "references"
            / "state-and-evidence.md"
        ).read_text(encoding="utf-8")
        self.assertIn("task-wide source-repair", closed_loop)
        self.assertIn("budget", closed_loop)
        self.assertIn("pending_fix_superseded", state_contract)
        self.assertIn("replayable history", state_contract)

        adapter_contract = (
            PLUGIN_ROOT
            / "skills"
            / "run-closed-loop-verification"
            / "references"
            / "project-adapter.md"
        ).read_text(encoding="utf-8")
        self.assertIn("A generic adapter may declare empty evidence arrays", adapter_contract)
        self.assertIn("Campaign journal/state ownership", adapter_contract)
        self.assertIn("same bounded bytes that established each scope hash", adapter_contract)


class HandoffFileChannelTests(unittest.TestCase):
    """The shared authoring contract owns the only GOAL handoff channel."""

    AUTHORED = ("draft-consensus-goal",)

    def _skill(self, name: str) -> str:
        return (PLUGIN_ROOT / "skills" / name / "SKILL.md").read_text(
            encoding="utf-8"
        )

    def test_channel_is_limited_to_the_sole_goal_authoring_skill(self) -> None:
        for skill in EXPECTED_SKILLS:
            text = self._skill(skill)
            if skill in self.AUTHORED:
                self.assertIn("goal-authoring.md", text, msg=skill)
            else:
                self.assertNotIn("goal-authoring.md", text, msg=skill)

        authoring = (PLUGIN_ROOT / "references" / "goal-authoring.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(".steward/handoffs/", authoring)
        self.assertIn("](handoff-file.md)", authoring)

    def test_writes_are_ordered_after_machine_validation(self) -> None:
        authoring = (PLUGIN_ROOT / "references" / "goal-authoring.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("after the GOAL validates", authoring)
        self.assertIn("before the canonical", authoring)
        self.assertIn("objective that references it is returned", authoring)

        contract = (PLUGIN_ROOT / "references" / "handoff-file.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("校验通过之后才开始写盘", contract)
        self.assertIn("磁盘保持原样", contract)

    def test_failed_location_check_preserves_each_requested_product(self) -> None:
        authoring = (PLUGIN_ROOT / "references" / "goal-authoring.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "A failed placement check removes the\nreference sentence",
            authoring,
        )
        self.assertIn("requires revalidation", authoring)
        self.assertIn("do not create a placeholder", authoring)
        self.assertIn("handoff or emit an invalid objective", authoring)
        self.assertIn("required handoff blocks", self._skill("draft-consensus-goal"))

    def test_draft_keeps_the_canonical_seven_line_output(self) -> None:
        draft = self._skill("draft-consensus-goal")
        self.assertIn("no JSON, digest, introduction, or text after the seventh line", draft)

        authoring = (PLUGIN_ROOT / "references" / "goal-authoring.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("or an eighth line", authoring)

        contract = (PLUGIN_ROOT / "references" / "handoff-file.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("可删除 .steward/handoffs/ 子树", contract)
        self.assertIn("不得据此删除整个 .steward/", contract)

    def test_a_failed_write_never_leaves_a_dangling_reference(self) -> None:
        # The write lands after validation, so by then the reference line is
        # already in the body; failing to write must retract it, not ship it.
        contract = (PLUGIN_ROOT / "references" / "handoff-file.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("写盘任一步失败时", contract)
        self.assertIn("把引用句从“证据与上下文”撤回", contract)
        self.assertIn("重新交给验证器校验", contract)
        self.assertIn("先回滚本轮已新建且内容仍未变", contract)
        self.assertIn("回滚不完整时报出实际错误和残留路径", contract)
        self.assertIn("带着悬空引用交付比没有附件更糟", contract)

    def test_contract_pins_the_location_gate_and_its_mechanical_reason(self) -> None:
        contract = (PLUGIN_ROOT / "references" / "handoff-file.md").read_text(
            encoding="utf-8"
        )
        for probe in (
            "git rev-parse --show-toplevel",
            "git ls-files --error-unmatch",
            "git check-ignore -q",
            "内容恰为一行 `*`",
        ):
            self.assertIn(probe, contract)

        # The ignore requirement is mechanical, not stylistic: the closed-loop
        # source inventory fingerprints non-ignored untracked entries.
        self.assertIn("--cached --others --exclude-standard", contract)
        self.assertIn("source drift", contract)
        self.assertIn("`INVALIDATED`", contract)

        adapter_contract = (
            PLUGIN_ROOT
            / "skills"
            / "run-closed-loop-verification"
            / "references"
            / "project-adapter.md"
        ).read_text(encoding="utf-8")
        self.assertIn("non-ignored untracked entries", adapter_contract)

        # The runtime handoff never escapes its one documented subtree, even
        # when the caller names another already-ignored project path.
        self.assertIn(
            "前两段必须精确为 `.steward/handoffs`", contract
        )
        self.assertIn("其他路径即使已被 git 忽略也不使用", contract)
        self.assertIn(
            "交接文件和忽略规则都只写在 `.steward/handoffs/`",
            contract,
        )
        self.assertIn("不得在 `.steward/` 根写入", contract)

    def test_handoff_ignore_rule_does_not_hide_control_plane_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(
                ["git", "init", "-q", str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            workflow = root / ".steward"
            handoffs = workflow / "handoffs"
            handoffs.mkdir(parents=True)
            (handoffs / ".gitignore").write_text("*\n", encoding="utf-8")
            (handoffs / "context.md").write_text("background\n", encoding="utf-8")
            (workflow / "invariants.json").write_text("{}\n", encoding="utf-8")

            status = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "status",
                    "--short",
                    "--untracked-files=all",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertNotIn("handoffs", status)
            self.assertIn("?? .steward/invariants.json", status)
            self.assertEqual(
                0,
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "check-ignore",
                        "-q",
                        "--",
                        ".steward/handoffs/context.md",
                    ],
                    check=False,
                ).returncode,
            )
            self.assertEqual(
                1,
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "check-ignore",
                        "-q",
                        "--",
                        ".steward/invariants.json",
                    ],
                    check=False,
                ).returncode,
            )

    def test_contract_bounds_authority_sandbox_and_file_content(self) -> None:
        contract = (PLUGIN_ROOT / "references" / "handoff-file.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("不为这次写入扩大沙箱或审批策略", contract)
        # Both writes are creates. An existing .gitignore at that path is a
        # signal the directory is taken, never something to overwrite.
        self.assertIn("已经有文件时不覆盖、不追加、不删除", contract)
        self.assertIn("不是改写任何既有文件", contract)
        self.assertIn("不写授权、停止或完成判定的措辞", contract)
        self.assertIn("`C*` 编号、验证 case ID、adapter 路径或 digest", contract)
        # The reference line shares one logical field line with the rest of
        # "证据与上下文"; the seven-line contract admits no extra line.
        self.assertIn("引用句不另起一行", contract)
        self.assertIn("读不到时按本字段其余来源自行核实", contract)

    def test_channel_is_documented_where_it_is_promised(self) -> None:
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        contract_index = (
            PLUGIN_ROOT / "references" / "control-plane-contracts.md"
        ).read_text(encoding="utf-8")

        self.assertIn("](references/handoff-file.md)", readme)
        self.assertIn(".steward/handoffs/", readme)
        self.assertIn("`draft-consensus-goal` 是唯一 GOAL 作者且禁止隐式调用", readme)
        self.assertIn("](handoff-file.md)", contract_index)
        self.assertIn(
            "The sole `draft-consensus-goal` authoring skill",
            contract_index,
        )
        self.assertIn("not a full-loop handoff", contract_index)
        self.assertIn(
            "out of the Git source inventory precisely because it is ignored",
            contract_index,
        )
        self.assertIn(
            "sibling control-plane files retain their existing Git behavior",
            contract_index,
        )

if __name__ == "__main__":
    unittest.main()
