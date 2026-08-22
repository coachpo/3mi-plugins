#!/usr/bin/env python3
"""Resolve the project document language and one path per canonical document."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DocumentLanguage(Enum):
    """The one language shared by every managed anchor and asset in a project."""

    CHINESE = "zh"
    ENGLISH = "en"

    @property
    def label(self) -> str:
        return "简体中文" if self is DocumentLanguage.CHINESE else "英文"


DEFAULT_LANGUAGE = DocumentLanguage.CHINESE

LANGUAGE_OPTIONS = {
    "zh": DocumentLanguage.CHINESE,
    "en": DocumentLanguage.ENGLISH,
}


def add_language_argument(parser) -> None:
    """Let a caller state the document language before any canonical file exists."""

    parser.add_argument(
        "--language",
        choices=tuple(LANGUAGE_OPTIONS),
        help=(
            "显式指定项目文档语言；省略时从已存在的固定文档路径判定，"
            "都不存在时按简体中文。与已存在文档的语言冲突时报错。"
        ),
    )


def requested_language(value: str | None) -> DocumentLanguage | None:
    return LANGUAGE_OPTIONS[value] if value else None


@dataclass(frozen=True)
class CanonicalDocument:
    key: str
    label: str
    chinese_path: str
    english_path: str
    template_token: str

    def path_for(self, language: DocumentLanguage) -> str:
        if language is DocumentLanguage.ENGLISH:
            return self.english_path
        return self.chinese_path


CANONICAL_DOCUMENTS = (
    CanonicalDocument(
        "product",
        "产品说明",
        "docs/产品说明.md",
        "docs/product.md",
        "PRODUCT_DOC",
    ),
    CanonicalDocument(
        "architecture",
        "架构说明",
        "docs/架构说明.md",
        "docs/architecture.md",
        "ARCHITECTURE_DOC",
    ),
    CanonicalDocument(
        "development_rules",
        "开发规范",
        "docs/开发规范.md",
        "docs/development-rules.md",
        "DEVELOPMENT_RULES_DOC",
    ),
    CanonicalDocument(
        "source_size_rules",
        "源代码规模与职责规则",
        "docs/源代码规模与职责规则.md",
        "docs/source-code-size-and-responsibility-rules.md",
        "SOURCE_SIZE_RULES_DOC",
    ),
)

ALWAYS_REQUIRED_PATHS = (
    "README.md",
    "STATUS.md",
    "CONTRIBUTING.md",
    "docs/README.md",
)

TOKEN_RE = re.compile(r"\{\{[A-Z_]+\}\}")


def path_is_present(path: Path) -> bool:
    """Treat broken symlinks as present so validation can report them precisely."""

    return path.exists() or path.is_symlink()


def language_evidence(root: Path) -> dict[DocumentLanguage, list[str]]:
    """Group existing canonical paths by the language their filename implies."""

    evidence: dict[DocumentLanguage, list[str]] = {}
    for document in CANONICAL_DOCUMENTS:
        chinese_present = path_is_present(root / document.chinese_path)
        english_present = path_is_present(root / document.english_path)
        if chinese_present and english_present:
            # select_canonical_paths reports this authority's conflict already;
            # a doubled authority carries no usable language signal.
            continue
        if chinese_present:
            evidence.setdefault(DocumentLanguage.CHINESE, []).append(
                document.chinese_path
            )
        elif english_present:
            evidence.setdefault(DocumentLanguage.ENGLISH, []).append(
                document.english_path
            )
    return evidence


def describe_evidence(evidence: dict[DocumentLanguage, list[str]]) -> str:
    return "；".join(
        f"{language.label}：{'、'.join(paths)}"
        for language, paths in sorted(
            evidence.items(), key=lambda item: item[0].value
        )
    )


def detect_document_language(root: Path) -> tuple[DocumentLanguage, list[str]]:
    """Infer the project's one document language from existing canonical paths."""

    evidence = language_evidence(root)
    if not evidence:
        return DEFAULT_LANGUAGE, []
    if len(evidence) == 1:
        return next(iter(evidence)), []
    return DEFAULT_LANGUAGE, [
        "固定文档同时使用中文和英文路径，无法确定项目文档语言："
        f"{describe_evidence(evidence)}；必须统一为同一种语言后再运行写入脚本"
    ]


def select_canonical_paths(
    root: Path,
    *,
    require_existing: bool = True,
    language: DocumentLanguage | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Select one path per authority, defaulting missing ones to the project language."""

    errors: list[str] = []
    if language is None:
        language, language_errors = detect_document_language(root)
        errors.extend(language_errors)

    selected: dict[str, str] = {}
    for document in CANONICAL_DOCUMENTS:
        candidates = (document.chinese_path, document.english_path)
        present = [
            relative
            for relative in candidates
            if path_is_present(root / relative)
        ]
        if len(present) > 1:
            errors.append(
                f"{document.label}同时存在中文和英文 canonical 文件："
                f"{document.chinese_path}、{document.english_path}；必须只保留一个"
            )
            selected[document.key] = document.path_for(language)
        elif present:
            selected[document.key] = present[0]
        else:
            selected[document.key] = document.path_for(language)
            if require_existing:
                errors.append(
                    f"缺少固定文档：{document.chinese_path} 或 "
                    f"{document.english_path}"
                )
    return selected, errors


@dataclass(frozen=True)
class ProjectDocsContext:
    """The resolved language and paths every managed write shares."""

    language: DocumentLanguage
    selected: dict[str, str]
    errors: list[str]
    language_errors: list[str]

    @property
    def language_resolved(self) -> bool:
        """False while anchor and asset checks would rest on a guessed language."""

        return not self.language_errors


def requested_language_errors(
    root: Path, language: DocumentLanguage
) -> list[str]:
    """Reject an explicit language that contradicts existing canonical files."""

    conflicting = {
        candidate: paths
        for candidate, paths in language_evidence(root).items()
        if candidate is not language
    }
    if not conflicting:
        return []
    return [
        f"指定的项目文档语言（{language.label}）与已存在的固定文档冲突："
        f"{describe_evidence(conflicting)}；改换语言是迁移任务，"
        "须整套文档一并迁移后再写入"
    ]


def resolve_project_docs(
    root: Path,
    *,
    require_existing: bool = True,
    language: DocumentLanguage | None = None,
) -> ProjectDocsContext:
    """Resolve language and canonical paths once for a single managed operation."""

    if language is None:
        language, language_errors = detect_document_language(root)
    else:
        language_errors = requested_language_errors(root, language)
    errors = list(language_errors)
    selected, path_errors = select_canonical_paths(
        root, require_existing=require_existing, language=language
    )
    errors.extend(path_errors)
    return ProjectDocsContext(
        language=language,
        selected=selected,
        errors=errors,
        language_errors=language_errors,
    )


def render_template(data: bytes, selected: dict[str, str], label: str) -> bytes:
    """Replace only declared canonical-path tokens in a UTF-8 managed asset."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} 不是有效 UTF-8") from error

    for document in CANONICAL_DOCUMENTS:
        token = "{{" + document.template_token + "}}"
        basename_token = "{{" + document.template_token + "_BASENAME}}"
        text = text.replace(token, selected[document.key])
        text = text.replace(basename_token, Path(selected[document.key]).name)

    unresolved = sorted(set(TOKEN_RE.findall(text)))
    if unresolved:
        raise ValueError(f"{label} 含有未知模板变量：{', '.join(unresolved)}")
    return text.encode("utf-8")


def canonical_path_mappings(
    selected: dict[str, str],
) -> tuple[tuple[str, str], ...]:
    """Map each unselected bilingual counterpart to the project's selected path."""

    mappings: list[tuple[str, str]] = []
    for document in CANONICAL_DOCUMENTS:
        chosen = selected[document.key]
        for candidate in (document.chinese_path, document.english_path):
            if candidate != chosen:
                mappings.append((candidate, chosen))
    return tuple(mappings)
