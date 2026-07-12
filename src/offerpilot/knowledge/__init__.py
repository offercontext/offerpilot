"""Knowledge Imported Source Ingest 领域服务。

KI-02 范围：Markdown 上传 + Extraction + Evidence + FTS 搜索。
"""

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
from offerpilot.knowledge.service import IngestRequest, KnowledgeIngestService
from offerpilot.knowledge.worker import ExtractionWorker

__all__ = [
    "EXTRACTOR_VERSION",
    "EvidenceRecord",
    "EvidenceSearchHit",
    "ExtractionWorker",
    "IngestRequest",
    "KnowledgeIngestService",
    "KnowledgeRepository",
    "MarkdownExtraction",
    "MarkdownExtractor",
    "SourceRecord",
    "SourceSnapshotRecord",
    "compute_source_hash",
]
