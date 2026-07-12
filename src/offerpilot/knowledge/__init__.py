"""Knowledge Imported Source Ingest 领域服务。

KI-03 范围：Markdown/Text 上传 + 粘贴正文 + 结构感知 Extraction + Evidence + FTS。
KI-04 范围：Source Bundle（Markdown 主文件 + PNG/JPEG/WebP 附件）+ Asset Evidence。
"""

from offerpilot.knowledge.assets import (
    AssetInput,
    AssetValidationError,
    VerifiedAsset,
)
from offerpilot.knowledge.encoding import (
    DecodedContent,
    EncodingError,
    decode_source_bytes,
)
from offerpilot.knowledge.extractor import (
    EXTRACTOR_VERSION,
    MarkdownExtraction,
    MarkdownExtractor,
    compute_bundle_source_hash,
    compute_source_hash,
)
from offerpilot.knowledge.repository import (
    AssetCreateInput,
    EvidenceRecord,
    EvidenceSearchHit,
    KnowledgeRepository,
    SourceAssetRecord,
    SourceRecord,
    SourceSnapshotRecord,
)
from offerpilot.knowledge.service import IngestError, IngestRequest, KnowledgeIngestService
from offerpilot.knowledge.tokenizer import TOKENIZER_VERSION, count_tokens
from offerpilot.knowledge.worker import ExtractionWorker

__all__ = [
    "AssetCreateInput",
    "AssetInput",
    "AssetValidationError",
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
    "SourceAssetRecord",
    "SourceRecord",
    "SourceSnapshotRecord",
    "TOKENIZER_VERSION",
    "VerifiedAsset",
    "compute_bundle_source_hash",
    "compute_source_hash",
    "count_tokens",
    "decode_source_bytes",
]
