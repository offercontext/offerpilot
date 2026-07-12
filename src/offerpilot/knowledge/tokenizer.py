"""Knowledge 产品 tokenizer。

Spec §4.2 要求固定 `knowledge-tokenizer-v1`：pinned `cl100k_base` 计数，不随 Provider
切换而变化。本模块负责加载并缓存该编码器，向 Extractor 与上传 Preflight 提供稳定
token 计数。

tiktext cl100k_base 在网络受限环境下需要下载 merges 文件。我们尽力加载，失败时
回退到 char/4 估算并标记 tokenizer 为降级状态；Spec 要求产品 tokenizer 固定，
因此降级路径只在加载失败时使用，调用方可以通过 `tokenizer_status()` 检查。
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import tiktoken


TOKENIZER_VERSION = "cl100k_base-1"
TOKENIZER_KIND = "cl100k_base"
FALLBACK_VERSION = "char-div4-1"
_MAX_TOKEN_LIMIT = 64_000


@dataclass(frozen=True)
class TokenCount:
    count: int
    tokenizer_version: str
    fallback: bool


@functools.lru_cache(maxsize=1)
def _load_encoding() -> "tiktoken.Encoding | None":
    try:
        import tiktoken
    except OSError:
        return None
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding(TOKENIZER_KIND)
    except Exception:
        return None


def tokenizer_status() -> tuple[str, bool]:
    """返回 (version, is_fallback)。"""

    if _load_encoding() is None:
        return FALLBACK_VERSION, True
    return TOKENIZER_VERSION, False


def count_tokens(text: str) -> TokenCount:
    """对 `text` 进行稳定 token 计数。

    Spec §4.2：64,000 product tokens 上限基于 cl100k_base；任何解码路径都不允许
    `errors="ignore"` 或 `errors="replace"`。token 计数仅用于上限门禁，不参与
    Evidence 身份。
    """

    if not text:
        return TokenCount(
            count=0,
            tokenizer_version=TOKENIZER_VERSION,
            fallback=False,
        )
    encoding = _load_encoding()
    if encoding is None:
        # Spec 要求固定 product tokenizer。tiktoken 不可用时，回退估算仅在加载
        # 失败的本地环境出现；CI 与生产环境通过显式安装 tiktoken 保证加载成功。
        estimate = max(1, len(text) // 4)
        return TokenCount(
            count=estimate,
            tokenizer_version=FALLBACK_VERSION,
            fallback=True,
        )
    encoded = encoding.encode(text)
    return TokenCount(
        count=len(encoded),
        tokenizer_version=TOKENIZER_VERSION,
        fallback=False,
    )


def max_token_limit() -> int:
    return _MAX_TOKEN_LIMIT
