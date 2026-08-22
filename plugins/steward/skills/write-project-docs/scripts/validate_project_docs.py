#!/usr/bin/env python3
"""Validate a project's canonical documentation set without modifying it."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

GUIDE_SCRIPTS = Path(__file__).resolve().parents[2] / "write-agent-guides" / "scripts"
if str(GUIDE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(GUIDE_SCRIPTS))

from canonical_paths import (
    ALWAYS_REQUIRED_PATHS,
    CANONICAL_DOCUMENTS,
    ProjectDocsContext,
    add_language_argument,
    canonical_path_mappings,
    render_template,
    requested_language,
    resolve_project_docs,
)
from contributing_blocks import (
    MvpMode,
    compose_contributing_block,
    mvp_heading_positions,
    parse_mvp_mode,
    render_contributing_assets,
)
from doc_anchors import profile_for
from iteration_strategy import validate_iteration_strategy_document  # noqa: E402
from managed_blocks import (
    ManagedBlockError,
    locate_managed_block,
    markdown_h1_lines,
)
from validate_engineering_router import validate_engineering_router  # noqa: E402


COMPETING_PATHS = (
    "docs/INDEX.md",
    "docs/通用工程规范.md",
    "docs/general-engineering-rules.md",
)

IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "target",
}

CONTRIBUTING_START_MARKER = (
    "<!-- write-project-docs:shared-contributing:start -->"
)
CONTRIBUTING_END_MARKER = (
    "<!-- write-project-docs:shared-contributing:end -->"
)
AGENTS_START_MARKER = "<!-- write-project-docs:document-navigation:start -->"
AGENTS_END_MARKER = "<!-- write-project-docs:document-navigation:end -->"
DEVELOPMENT_START_MARKER = (
    "<!-- write-project-docs:development-source-size:start -->"
)
DEVELOPMENT_END_MARKER = (
    "<!-- write-project-docs:development-source-size:end -->"
)
LEGACY_DOC_PATHS = (
    "docs/INDEX.md",
)

INLINE_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^)\s]+)(?:\s+['\"][^)]*)?\)"
)
REFERENCE_LINK_RE = re.compile(
    r"^\s*\[[^\]]+\]:\s*(?P<target><[^>]+>|\S+)", re.MULTILINE
)
_THRESHOLD_VALUE = r"(?<!\d)`?(?:240|300|50)`?(?!\d)"
_THRESHOLD_UNIT = r"(?:行|lines?)"
_THRESHOLD_COMPARATOR = (
    r"超过|大于|达到|约|不少于|>=?|≤|"
    r"over|more than|no more than|greater than|larger than|longer than|"
    r"exceeds?|exceeding|at least|at most|up to|under|below|beyond|"
    r"about|around|approximately|reach(?:es|ing)?"
)
_THRESHOLD_LIMIT_WORD = r"阈值|上限|限制|limits?|thresholds?|caps?|maximum|max"
THRESHOLD_RE = re.compile(
    rf"(?:(?:{_THRESHOLD_COMPARATOR})\s*{_THRESHOLD_VALUE}\s*{_THRESHOLD_UNIT}|"
    rf"{_THRESHOLD_VALUE}\s*{_THRESHOLD_UNIT}\s*(?:{_THRESHOLD_LIMIT_WORD})|"
    rf"{_THRESHOLD_VALUE}-line\s+(?:{_THRESHOLD_LIMIT_WORD}))",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "验证固定项目文档的中英文 canonical 路径、共享内容、"
            "开发规范专项引用、根 AGENTS.md 文档区块和本地 Markdown 链接。"
        )
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="项目根目录，默认为当前目录。",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "把旧 canonical 路径、嵌套 AGENTS.md 引用、可能重复规则等迁移警告"
            "视为失败；共享内容缺失、漂移或区块边界错误在普通模式也会失败。"
        ),
    )
    parser.add_argument(
        "--profiles-root",
        help="可选的架构 profile 包根目录；默认使用插件捆绑资源。",
    )
    add_language_argument(parser)
    return parser.parse_args()


def markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.md"):
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if path.is_file() and not path.is_symlink():
            files.append(path)
    return sorted(files)


def display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def extract_link_targets(text: str) -> list[str]:
    targets = [match.group("target") for match in INLINE_LINK_RE.finditer(text)]
    targets.extend(match.group("target") for match in REFERENCE_LINK_RE.finditer(text))
    return targets


def legacy_path_references(
    text: str, selected: dict[str, str] | None
) -> list[tuple[int, str]]:
    """Report stale paths; without a resolved language only fixed ones qualify."""

    references: list[tuple[int, str]] = []
    stale_paths = LEGACY_DOC_PATHS
    if selected is not None:
        stale_paths += tuple(
            old_path for old_path, _ in canonical_path_mappings(selected)
        )
    for line_number, line in enumerate(text.splitlines(), start=1):
        for legacy_path in stale_paths:
            if legacy_path in line:
                references.append((line_number, legacy_path))
    return references


def complete_managed_asset_issue(
    data: bytes, start_marker: str, end_marker: str, label: str
) -> str | None:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return f"{label} 不是有效 UTF-8"
    if b"\r" in data or not data.endswith(b"\n") or data.endswith(b"\n\n"):
        return f"{label} 必须使用 LF，并保留且仅保留一个尾随换行"
    try:
        span = locate_managed_block(
            data, start_marker.encode(), end_marker.encode(), label
        )
    except ManagedBlockError as error:
        return str(error)
    if span is None:
        return f"{label} 缺少 marker"
    if span.start != 0 or span.end != len(data):
        return f"{label} 的 marker 必须包围整个 asset"
    return None


def validate_link(source: Path, raw_target: str, root: Path) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    if not target or target.startswith("#"):
        return None

    parsed = urlsplit(target)
    if parsed.scheme or target.startswith("//") or target.startswith("/"):
        return None

    relative_path = unquote(parsed.path)
    if not relative_path:
        return None

    resolved = (source.parent / relative_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return f"{display_path(source, root)}: 链接越出项目根目录：{raw_target}"

    if not resolved.exists():
        return f"{display_path(source, root)}: 本地链接目标不存在：{raw_target}"
    return None


def check_language_anchors(
    root: Path, skill_root: Path, context: ProjectDocsContext
) -> tuple[list[str], list[str]]:
    """Check the anchors, assets and managed blocks of the resolved language."""

    errors: list[str] = []
    warnings: list[str] = []
    selected = context.selected
    profile = profile_for(context.language)

    mvp_mode: MvpMode | None = None
    status_path = root / "STATUS.md"
    if status_path.is_file() and not status_path.is_symlink():
        try:
            status_text = status_path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            errors.append("STATUS.md 不是有效 UTF-8")
        else:
            try:
                mvp_mode = parse_mvp_mode(status_text, context.language)
            except ValueError as error:
                errors.append(str(error))

    for relative in selected.values():
        path = root / relative
        if path.is_symlink():
            errors.append(f"固定文档不得使用符号链接：{relative}")
        elif path.exists() and not path.is_file():
            errors.append(f"固定文档必须是普通文件：{relative}")

    development_rules = root / selected["development_rules"]
    if development_rules.is_file() and not development_rules.is_symlink():
        try:
            development_text = development_rules.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            pass
        else:
            development_title = profile.development_rules_title
            has_canonical_prefix = (
                development_text == development_title
                or development_text.startswith(development_title + "\n")
            )
            if (
                not has_canonical_prefix
                or markdown_h1_lines(development_text) != [development_title]
            ):
                errors.append(
                    f"{selected['development_rules']} 必须以唯一的"
                    f"“{development_title}”标题开头"
                )

    development_asset = profile.asset_path(
        skill_root, profile.development_asset_name
    )
    development_asset_issue: str | None = None
    if development_asset.is_symlink() or not development_asset.is_file():
        errors.append(
            "skill 缺少普通共享资源："
            + profile.asset_display(profile.development_asset_name)
        )
    else:
        try:
            expected_development_block = render_template(
                development_asset.read_bytes(),
                selected,
                "开发规范规模规则 asset",
            )
        except ValueError as error:
            errors.append(f"skill 共享资源无效：{error}")
            expected_development_block = b""
        development_asset_issue = complete_managed_asset_issue(
            expected_development_block,
            DEVELOPMENT_START_MARKER,
            DEVELOPMENT_END_MARKER,
            "开发规范规模规则 asset",
        )
        if development_asset_issue:
            errors.append(f"skill 共享资源无效：{development_asset_issue}")
    if (
        development_asset.is_file()
        and not development_asset.is_symlink()
        and not development_asset_issue
        and development_rules.is_file()
        and not development_rules.is_symlink()
    ):
        actual_development = development_rules.read_bytes()
        try:
            span = locate_managed_block(
                actual_development,
                DEVELOPMENT_START_MARKER.encode(),
                DEVELOPMENT_END_MARKER.encode(),
                "开发规范的规模规则引用区块",
            )
        except ManagedBlockError as error:
            errors.append(str(error))
        else:
                if span is None:
                    errors.append(
                        f"{selected['development_rules']} 缺少规模规则引用区块"
                    )
                elif actual_development[: span.start] not in {
                    (profile.development_rules_title + "\n\n").encode("utf-8"),
                    (profile.development_rules_title + "\r\n\r\n").encode("utf-8"),
                }:
                    errors.append(
                        f"{selected['development_rules']} 的规模规则引用区块"
                        "必须紧跟标题"
                    )
                elif (
                    actual_development[span.start : span.end]
                    != expected_development_block
                    or actual_development.count(expected_development_block) != 1
                ):
                    errors.append(
                        f"{selected['development_rules']} 的规模规则引用区块"
                        "已漂移，必须用 asset 完整替换"
                    )

    source_asset = profile.asset_path(
        skill_root, profile.source_size_asset_name
    )
    project_source_rules = root / selected["source_size_rules"]
    if source_asset.is_symlink() or not source_asset.is_file():
        errors.append(
            "skill 缺少普通共享资源："
            + profile.asset_display(profile.source_size_asset_name)
        )
    elif project_source_rules.is_file():
        try:
            expected_source_rules = render_template(
                source_asset.read_bytes(), selected, "源代码规模与职责规则 asset"
            )
        except ValueError as error:
            errors.append(f"skill 共享资源无效：{error}")
        else:
            if project_source_rules.read_bytes() != expected_source_rules:
                errors.append(
                    f"{selected['source_size_rules']} 与 skill asset 的路径渲染结果"
                    "不一致"
                )

    contributing_asset = profile.asset_path(
        skill_root, profile.contributing_base_asset_name
    )
    contributing_mvp_asset = profile.asset_path(
        skill_root, profile.contributing_mvp_asset_name
    )
    contributing = root / "CONTRIBUTING.md"
    asset_issue: str | None = None
    expected_base_block = b""
    expected_mvp_block = b""
    expected_contributing_block = b""
    base_asset_ready = (
        contributing_asset.is_file() and not contributing_asset.is_symlink()
    )
    mvp_asset_ready = (
        contributing_mvp_asset.is_file()
        and not contributing_mvp_asset.is_symlink()
    )
    if not base_asset_ready:
        errors.append(
            "skill 缺少普通共享资源："
            + profile.asset_display(profile.contributing_base_asset_name)
        )
    if not mvp_asset_ready:
        errors.append(
            "skill 缺少普通共享资源："
            + profile.asset_display(profile.contributing_mvp_asset_name)
        )
    if base_asset_ready and mvp_asset_ready:
        try:
            expected_base_text, expected_mvp_text = render_contributing_assets(
                contributing_asset.read_bytes(),
                contributing_mvp_asset.read_bytes(),
                selected,
                context.language,
            )
        except ValueError as error:
            asset_issue = str(error)
            errors.append(f"skill 共享资源无效：{error}")
        else:
            expected_base_block = expected_base_text.encode("utf-8")
            expected_mvp_block = expected_mvp_text.encode("utf-8")
    if (
        not asset_issue
        and expected_base_block
        and expected_mvp_block
        and mvp_mode is not None
    ):
        try:
            expected_contributing_text = compose_contributing_block(
                expected_base_block.decode("utf-8"),
                expected_mvp_block.decode("utf-8"),
                mvp_mode=mvp_mode,
                language=context.language,
            )
        except (UnicodeDecodeError, ValueError) as error:
            asset_issue = str(error)
            errors.append(f"skill 共享资源无效：{error}")
        else:
            expected_contributing_block = expected_contributing_text.encode("utf-8")
            asset_issue = complete_managed_asset_issue(
                expected_contributing_block,
                CONTRIBUTING_START_MARKER,
                CONTRIBUTING_END_MARKER,
                "CONTRIBUTING 组合 asset",
            )
            if asset_issue:
                errors.append(f"skill 共享资源无效：{asset_issue}")
    if (
        contributing_asset.is_file()
        and not contributing_asset.is_symlink()
        and not asset_issue
        and expected_contributing_block
        and contributing.is_file()
        and not contributing.is_symlink()
    ):
        try:
            actual_contributing_text = contributing.read_bytes().decode("utf-8")
            expected_contributing_text = expected_contributing_block.decode("utf-8")
        except UnicodeDecodeError:
            errors.append("CONTRIBUTING.md 不是有效 UTF-8")
        else:
            try:
                span = locate_managed_block(
                    actual_contributing_text,
                    CONTRIBUTING_START_MARKER,
                    CONTRIBUTING_END_MARKER,
                    "CONTRIBUTING.md 的共享区块",
                )
            except ManagedBlockError as error:
                errors.append(str(error))
            else:
                mvp_positions = mvp_heading_positions(
                    actual_contributing_text, profile
                )
                if span is None:
                    errors.append("CONTRIBUTING.md 缺少共享 contribution asset")
                    if mvp_positions:
                        errors.append(
                            "CONTRIBUTING.md 在托管区块外包含"
                            f"“{profile.mvp_heading}”"
                        )
                else:
                    outside_mvp = [
                        position
                        for position in mvp_positions
                        if not (span.start <= position < span.end)
                    ]
                    inside_mvp = [
                        position
                        for position in mvp_positions
                        if span.start <= position < span.end
                    ]
                    if outside_mvp:
                        errors.append(
                            "CONTRIBUTING.md 在托管区块外包含"
                            f"“{profile.mvp_heading}”"
                        )
                    if len(inside_mvp) > 1:
                        errors.append(
                            "CONTRIBUTING.md 的共享区块包含重复"
                            f"“{profile.mvp_title}”标题"
                        )
                    if (
                        actual_contributing_text[span.start : span.end]
                        != expected_contributing_text
                        or actual_contributing_text.count(expected_contributing_text)
                        != 1
                    ):
                        errors.append(
                            "CONTRIBUTING.md 的共享区块已漂移，"
                            "必须用 asset 完整替换"
                        )

    if contributing.is_file() and not contributing.is_symlink():
        try:
            iteration_contributing_text = contributing.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            message = "CONTRIBUTING.md 不是有效 UTF-8"
            if message not in errors:
                errors.append(message)
        else:
            try:
                validate_iteration_strategy_document(
                    iteration_contributing_text,
                    root,
                    selected,
                    profile,
                )
            except (OSError, ValueError) as error:
                errors.append(str(error))

    agents_asset = profile.asset_path(skill_root, profile.agents_asset_name)
    root_agents = root / "AGENTS.md"
    agents_asset_issue: str | None = None
    if agents_asset.is_symlink() or not agents_asset.is_file():
        errors.append(
            "skill 缺少普通共享资源："
            + profile.asset_display(profile.agents_asset_name)
        )
    else:
        try:
            expected_agents_block = render_template(
                agents_asset.read_bytes(), selected, "AGENTS 文档区块 asset"
            )
        except ValueError as error:
            errors.append(f"skill 共享资源无效：{error}")
            expected_agents_block = b""
        agents_asset_issue = complete_managed_asset_issue(
            expected_agents_block,
            AGENTS_START_MARKER,
            AGENTS_END_MARKER,
            "AGENTS 文档区块 asset",
        )
        if agents_asset_issue:
            errors.append(f"skill 共享资源无效：{agents_asset_issue}")
    if (
        agents_asset.is_file()
        and not agents_asset.is_symlink()
        and not agents_asset_issue
        and root_agents.exists()
    ):
        if root_agents.is_symlink():
            warnings.append("根 AGENTS.md 是符号链接，未验证或管理其文档区块")
        elif not root_agents.is_file():
            warnings.append("根 AGENTS.md 不是普通文件，未验证或管理其文档区块")
        else:
            actual = root_agents.read_bytes()
            try:
                agents_text = actual.decode("utf-8")
                expected_agents_text = expected_agents_block.decode("utf-8")
            except UnicodeDecodeError:
                errors.append("AGENTS.md 不是有效 UTF-8")
                agents_text = actual.decode("utf-8", errors="replace")
            else:
                try:
                    span = locate_managed_block(
                        agents_text,
                        AGENTS_START_MARKER,
                        AGENTS_END_MARKER,
                        "根 AGENTS.md 的文档区块",
                    )
                except ManagedBlockError as error:
                    errors.append(str(error))
                else:
                    if span is None:
                        errors.append("现有根 AGENTS.md 缺少文档区块 asset")
                    elif (
                        agents_text[span.start : span.end]
                        != expected_agents_text
                        or agents_text.count(expected_agents_text) != 1
                    ):
                        errors.append(
                            "根 AGENTS.md 的文档区块已漂移，"
                            "必须用 asset 完整替换"
                        )
            for line_number, legacy_path in legacy_path_references(
                agents_text, selected
            ):
                errors.append(
                    f"AGENTS.md:{line_number}: 仍引用旧 canonical 路径：{legacy_path}"
                )

    return errors, warnings


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    skill_root = Path(__file__).resolve().parent.parent
    errors: list[str] = []
    warnings: list[str] = []

    if not root.is_dir():
        print(f"错误：项目根目录不存在或不是目录：{root}", file=sys.stderr)
        return 2

    docs_directory = root / "docs"
    if docs_directory.is_symlink():
        print("错误：")
        print("- docs 目录不得使用符号链接")
        return 1

    for relative in ALWAYS_REQUIRED_PATHS:
        path = root / relative
        if not path.is_file():
            errors.append(f"缺少固定文档：{relative}")
        elif path.is_symlink():
            errors.append(f"固定文档不得使用符号链接：{relative}")

    for relative in COMPETING_PATHS:
        if (root / relative).exists():
            warnings.append(f"存在竞争或遗留 canonical 路径：{relative}")

    context = resolve_project_docs(
        root, language=requested_language(args.language)
    )
    errors.extend(context.errors)
    router_errors = validate_engineering_router(
        root,
        profiles_root=Path(args.profiles_root) if args.profiles_root else None,
        language=args.language,
    )
    errors.extend(f"工程路由：{error}" for error in router_errors)
    # 语言未确定时，锚点和 asset 比对只会基于回退语言给出误导性结论；
    # 下面与语言无关的检查照常执行，一并报告。
    if context.language_resolved:
        selected: dict[str, str] | None = context.selected
        anchor_errors, anchor_warnings = check_language_anchors(
            root, skill_root, context
        )
        errors.extend(anchor_errors)
        warnings.extend(anchor_warnings)
        size_rule_paths = {
            context.selected["source_size_rules"],
            context.selected["architecture"],
        }
        development_rules_path: str | None = context.selected["development_rules"]
    else:
        selected = None
        size_rule_paths = {
            candidate
            for document in CANONICAL_DOCUMENTS
            if document.key in {"source_size_rules", "architecture"}
            for candidate in (document.chinese_path, document.english_path)
        }
        development_rules_path = None

    root_agents = root / "AGENTS.md"
    docs = markdown_files(root)
    for path in docs:
        try:
            path.relative_to(skill_root / "assets")
        except ValueError:
            pass
        else:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"{display_path(path, root)}: 不是有效 UTF-8 Markdown")
            continue
        for target in extract_link_targets(text):
            issue = validate_link(path, target, root)
            if issue:
                errors.append(issue)

        relative = path.relative_to(root).as_posix()
        if relative not in size_rule_paths:
            for line_number, line in enumerate(text.splitlines(), start=1):
                if THRESHOLD_RE.search(line):
                    message = (
                        f"{relative}:{line_number}: 可能重复了共享规模阈值；"
                        "应改为链接"
                    )
                    if relative == development_rules_path:
                        errors.append(message)
                    else:
                        warnings.append(message)

    for agents_path in sorted(root.rglob("AGENTS.md")):
        relative_path = agents_path.relative_to(root)
        if agents_path == root_agents or any(
            part in IGNORED_PARTS for part in relative_path.parts
        ):
            continue
        relative = relative_path.as_posix()
        if agents_path.is_symlink():
            warnings.append(f"{relative}: 嵌套 AGENTS.md 是符号链接，未检查旧路径")
            continue
        if not agents_path.is_file():
            continue
        try:
            agents_text = agents_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, legacy_path in legacy_path_references(agents_text, selected):
            warnings.append(
                f"{relative}:{line_number}: 嵌套 AGENTS.md 仍引用旧 canonical 路径："
                f"{legacy_path}"
            )

    if errors:
        print("错误：")
        for item in errors:
            print(f"- {item}")
    if warnings:
        print("警告：")
        for item in warnings:
            print(f"- {item}")
    if not errors and not warnings:
        print("项目文档验证通过。")
    elif not errors:
        print("项目文档基础验证通过，但仍有迁移警告。")

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
