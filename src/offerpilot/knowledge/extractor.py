"""Knowledge Markdown Extractor。

KI-02 范围：仅处理 Markdown happy path —— heading_path + paragraph。其他结构（list、
blockquote、table、fenced_code 等）由 KI-03 扩展。

- `compute_source_hash` 计算主文件字节的内容寻址 hash（KI-02 不考虑附件）。
- `MarkdownExtractor.extract` 用 markdown-it-py 解析 Markdown，规范化文本，并生成
  稳定 Evidence 列表（snapshot_digest + extractor_version + locator + content_hash）。
- 相同输入重复执行得到相同 Snapshot digest 和 Evidence ID。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token


EXTRACTOR_VERSION = "md-ki02-1"
PARSER_VERSION = "markdown-it-py-3"
NORMALIZATION_VERSION = "nl-1"
TOKENIZER_VERSION = "none-1"


_SOURCE_HASH_PREFIX = "sha256:"
MAX_FILE_BYTES = 5 * 1024 * 1024  # Spec §4.2 主 Markdown/Text 5 MiB
_MAX_TOKEN_COUNT = 64_000  # Spec §4.2 规范文本 64,000 product tokens
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def compute_source_hash(content_bytes: bytes) -> str:
    """KI-02 主文件字节级 source_hash。KI-05 会扩展到附件字节 + 逻辑路径。"""
    digest = hashlib.sha256(content_bytes).hexdigest()
    return f"{_SOURCE_HASH_PREFIX}{digest}"


@dataclass(frozen=True)
class EvidenceDraft:
    """Extractor 产出的 Evidence 草稿，由 Worker 写入数据库。"""

    block_kind: str
    heading_path: tuple[str, ...]
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    canonical_excerpt: str
    search_text: str
    content_hash: str
    locator: str


@dataclass(frozen=True)
class MarkdownExtraction:
    """Extractor 输出：canonical_text + digest + Evidence 草稿列表。"""

    canonical_text: str
    digest: str
    encoding: str
    detection_method: str
    evidence_drafts: list[EvidenceDraft]


class ExtractionError(Exception):
    """非暂时性 Extraction 失败，携带稳定 error_code。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _normalize_text(raw: str) -> str:
    """Spec §7.1 规范化：换行统一为 \\n，去除行尾空白，压缩多余空行。"""
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _TRAILING_WS_RE.sub("\n", normalized)
    normalized = _MULTI_NEWLINE_RE.sub("\n\n", normalized)
    return normalized


def estimate_tokens(text: str) -> int:
    """粗略 token 估算，作为 KI-02 上限门禁。

    Spec §4.2 要求固定 product tokenizer；KI-02 还没接入真实 tokenizer，先用 char/4 估
    算作为 hard cap，KI-03 接入 pinned cl100k_base 时再精确化。
    """
    return max(1, len(text) // 4)


def _heading_depth(token: Token) -> int:
    tag = token.tag or ""
    if tag.startswith("h") and tag[1:].isdigit():
        return int(tag[1:])
    return 0


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MarkdownExtractor:
    """解析 Markdown 并生成稳定 Evidence 草稿。"""

    def __init__(self) -> None:
        self._parser = MarkdownIt("commonmark", {"html": False}).disable("html_block", True)

    def extract(self, raw_content: str, *, encoding: str = "utf-8", detection_method: str = "bom-strict") -> MarkdownExtraction:
        canonical = _normalize_text(raw_content)
        if "\x00" in canonical:
            raise ExtractionError("encoding_unknown", "原文中存在 NUL 控制字符，无法安全解析")

        token_count = estimate_tokens(canonical)
        if token_count > _MAX_TOKEN_COUNT:
            raise ExtractionError(
                "source_too_large",
                f"原文估算约 {token_count} product tokens，超出 KI-02 暂行上限 {_MAX_TOKEN_COUNT}",
            )

        tokens = self._parser.parse(canonical)
        drafts = _walk_tokens(canonical, tokens)
        digest = _snapshot_digest(canonical)
        return MarkdownExtraction(
            canonical_text=canonical,
            digest=digest,
            encoding=encoding,
            detection_method=detection_method,
            evidence_drafts=drafts,
        )


def _snapshot_digest(canonical_text: str) -> str:
    payload = f"{EXTRACTOR_VERSION}|{NORMALIZATION_VERSION}|{PARSER_VERSION}|{canonical_text}"
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _walk_tokens(canonical_text: str, tokens: list[Token]) -> list[EvidenceDraft]:
    drafts: list[EvidenceDraft] = []
    heading_stack: list[tuple[int, str]] = []
    ordinal = 0
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token.type == "heading_open":
            depth = _heading_depth(token)
            inline = tokens[idx + 1] if idx + 1 < len(tokens) else None
            title = _inline_text(inline) if inline is not None else ""
            if depth > 0 and title:
                heading_stack = [(d, t) for d, t in heading_stack if d < depth]
                heading_stack.append((depth, title))
            idx += 3  # heading_open + inline + heading_close
            continue
        if token.type == "paragraph_open":
            inline = tokens[idx + 1] if idx + 1 < len(tokens) else None
            if inline is not None and inline.content:
                excerpt = inline.content
                start, end = _inline_char_range(inline, canonical_text)
                line_start, line_end = _line_range(canonical_text, start, end)
                heading_path = tuple(text for _, text in heading_stack)
                ordinal += 1
                drafts.append(
                    EvidenceDraft(
                        block_kind="paragraph",
                        heading_path=heading_path,
                        char_start=start,
                        char_end=end,
                        line_start=line_start,
                        line_end=line_end,
                        canonical_excerpt=excerpt,
                        search_text=inline.content,
                        content_hash=_content_hash(excerpt),
                        locator=f"paragraph:{line_start}:{start}",
                    )
                )
            idx += 3
            continue
        # 其他块类型（list/blockquote/table/fenced_code 等）由 KI-03 处理。
        idx += 1
    return drafts


def _inline_text(token: Token) -> str:
    if token.type == "inline":
        return token.content.strip()
    return ""


def _inline_char_range(token: Token, canonical_text: str) -> tuple[int, int]:
    start = token.map[0] if token.map else 0
    end_line = token.map[1] if token.map and len(token.map) > 1 else start + 1
    char_start = _line_offset(canonical_text, start)
    char_end = _line_offset(canonical_text, end_line)
    return char_start, min(char_end, len(canonical_text))


def _line_range(canonical_text: str, char_start: int, char_end: int) -> tuple[int, int]:
    line_start = canonical_text.count("\n", 0, char_start) + 1
    line_end = canonical_text.count("\n", 0, max(char_start, char_end - 1)) + 1
    return line_start, line_end


def _line_offset(canonical_text: str, line_index: int) -> int:
    if line_index <= 0:
        return 0
    offset = 0
    for _ in range(line_index):
        next_newline = canonical_text.find("\n", offset)
        if next_newline == -1:
            return len(canonical_text)
        offset = next_newline + 1
    return offset
