"""Knowledge Extraction Worker。

负责从不可变原件读取字节，调用 Encoding + Extractor 生成 Snapshot + Evidence 草稿，
并在单个 SQLAlchemy 事务中提交。Spec §9：事务失败时旧 Snapshot 仍可用；首次失败
Source 不可搜索。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from offerpilot.knowledge.encoding import DecodedContent, decode_source_bytes
from offerpilot.knowledge.extractor import MarkdownExtractor
from offerpilot.knowledge.repository import KnowledgeRepository


@dataclass(frozen=True)
class DecodedMarkdown(DecodedContent):
    """兼容旧类型名；KI-03 之后请直接使用 ``DecodedContent``。"""


def decode_markdown_bytes(raw_bytes: bytes) -> Optional[DecodedMarkdown]:
    """兼容 KI-02 接口的薄包装。新代码请直接使用 ``decode_source_bytes``。

    返回 ``None`` 表示编码识别失败；新 ``decode_source_bytes`` 会抛 ``EncodingError``。
    """

    try:
        result = decode_source_bytes(raw_bytes)
    except Exception:
        return None
    return DecodedMarkdown(
        text=result.text,
        encoding=result.encoding,
        detection_method=result.detection_method,
    )


class ExtractionWorker:
    """重跑 Extraction 时从原件重建 Snapshot/Evidence/FTS。

    KI-02 主路径在 service 层完成 Extraction，但 worker 保留给 KI-07 队列、未来重跑
    与单元测试幂等性验证。
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        data_dir: Path,
        session_factory: sessionmaker[Session],
        extractor: Optional[MarkdownExtractor] = None,
    ) -> None:
        self._repository = repository
        self._data_dir = data_dir
        self._session_factory = session_factory
        self._extractor = extractor or MarkdownExtractor()

    def can_decode(self, source: "object") -> bool:
        path = self._data_dir / getattr(source, "main_relative_path", "")
        if not path.is_file():
            return False
        return decode_markdown_bytes(path.read_bytes()) is not None
