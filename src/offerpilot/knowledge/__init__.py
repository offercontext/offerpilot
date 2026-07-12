"""Knowledge Imported Source Ingest 领域服务。

KI-03 范围：Markdown/Text 上传 + 粘贴正文 + 结构感知 Extraction + Evidence + FTS。
"""

from offerpilot.knowledge.encoding import (
    DecodedContent,
    EncodingError,
    decode_source_bytes,
)
from offerpilot.knowledge.extractor import (
    EXTRACTOR_VERSION,
    MarkdownExtraction,
    MarkdownExtractor,
    compute_source_hash,
)
from offerpilot.knowledge.repository import (
    EvidenceRecord,
    EvidenceSearchHit,
    KnowledgeRepository,
    SourceRecord,
    SourceSnapshotRecord,
)
from offerpilot.knowledge.service import IngestError, IngestRequest, KnowledgeIngestService
from offerpilot.knowledge.tokenizer import TOKENIZER_VERSION, count_tokens
from offerpilot.knowledge.worker import ExtractionWorker

__all__ = [
    "DecodedContent",
    "EXTRACTOR_VERSION",
    "EncodingError",
    "EvidenceRecord",
    "EvidenceSearchHit",
    "ExtractionWorker",
    "IngestError",
    "IngestRequest",
    "KnowledgeIngestService",
    "KnowledgeRepository",
    "MarkdownExtraction",
    "MarkdownExtractor",
    "SourceRecord",
    "SourceSnapshotRecord",
    "TOKENIZER_VERSION",
    "compute_source_hash",
    "count_tokens",
    "decode_source_bytes",
]
