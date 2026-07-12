"""Knowledge Extraction Worker。

负责从不可变原件读取 Markdown，调用 Extractor 生成 Snapshot + Evidence 草稿，并在单个
SQLAlchemy 事务中提交。Spec §9：事务失败时旧 Snapshot 仍可用；首次失败 Source 不可搜索。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from offerpilot.knowledge.extractor import MarkdownExtractor
from offerpilot.knowledge.repository import KnowledgeRepository


@dataclass(frozen=True)
class DecodedMarkdown:
    text: str
    encoding: str
    detection_method: str


def decode_markdown_bytes(raw_bytes: bytes) -> Optional[DecodedMarkdown]:
    """Spec §4.3：KI-02 只支持 UTF-8（含 BOM）。

    其他编码（UTF-16、GBK/GB18030）以及无 BOM 但非 UTF-8 的内容统一拒绝，KI-03 接入完整
    编码矩阵与置信度检测。本函数同时被 service（preflight 阶段）与 worker（重启重跑）
    使用，确保解码语义一致。
    """
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        try:
            text = raw_bytes[3:].decode("utf-8")
        except UnicodeDecodeError:
            return None
        return DecodedMarkdown(text=text, encoding="utf-8-sig", detection_method="bom-utf8")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return DecodedMarkdown(text=text, encoding="utf-8", detection_method="strict-utf8")


class ExtractionWorker:
    """重跑 Extraction 时从原件重建 Snapshot/Evidence/FTS。

    KI-02 主路径在 service 层完成 Extraction，但 worker 保留给 KI-07 队列、未来重跑与单元
    测试幂等性验证。
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


