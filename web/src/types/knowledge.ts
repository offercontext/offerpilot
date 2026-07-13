export interface KnowledgeEvidence {
  id: string;
  source_id: number;
  snapshot_id: number;
  kind: string;
  block_kind: string;
  ordinal: number;
  heading_path: string[];
  char_start: number;
  char_end: number;
  line_start: number;
  line_end: number;
  canonical_excerpt: string;
  search_text: string;
  content_hash: string;
  asset_id: number | null;
  previous_evidence_id: string | null;
  next_evidence_id: string | null;
}

export interface KnowledgeEvidencePage {
  items: KnowledgeEvidence[];
  next_cursor: number | null;
}

export interface KnowledgeSourceAsset {
  id: number;
  source_id: number;
  logical_name: string;
  media_type: string;
  relative_path: string;
  bytes: number;
  sha256: string;
  width: number;
  height: number;
  created_at: string;
}

export interface KnowledgeSourceAssetsResponse {
  items: KnowledgeSourceAsset[];
}

export interface KnowledgeSource {
  id: number;
  source_kind: string;
  title: string;
  display_title: string;
  title_hint: string;
  main_filename: string;
  main_media_type: string;
  total_bytes: number;
  token_count: number;
  lifecycle: string;
  extraction_status: string;
  extraction_error_code: string;
  extraction_error_message: string;
  brief_status: string;
  brief_block_reason: string;
  brief_error_code: string;
  brief_error_message: string;
  active_snapshot_id: number | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeJob {
  id: number;
  kind: string;
  queue: string;
  source_id: number | null;
  snapshot_id: number | null;
  stage: string;
  status: string;
  progress: number;
  retry_count: number;
  error_code: string;
  error_message: string;
  canceled: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeOrigin {
  id: number;
  source_id: number;
  import_method: string;
  original_filename: string;
  origin_url: string;
  imported_at: string;
}

export interface KnowledgeIngestResponse {
  deduplicated: boolean;
  source: KnowledgeSource;
  job: KnowledgeJob;
  extraction_error_code: string;
  extraction_error_message: string;
}

export interface KnowledgeEvidenceSearchHit {
  evidence_id: string;
  source_id: number;
  snapshot_id: number;
  block_kind: string;
  heading_path: string[];
  char_start: number;
  char_end: number;
  line_start: number;
  line_end: number;
  canonical_excerpt: string;
  snippet: string;
  score: number;
}

export interface KnowledgeEvidenceSearchResponse {
  query: string;
  hits: KnowledgeEvidenceSearchHit[];
}

export interface KnowledgeSourceJobsResponse {
  jobs: KnowledgeJob[];
  origins: KnowledgeOrigin[];
}

export interface KnowledgeDeleteJob {
  id: number;
  kind: 'delete';
  queue: 'extraction';
  source_id: number;
  snapshot_id: number | null;
  stage: string;
  status: string;
  progress: number;
  retry_count: number;
  error_code: string;
  error_message: string;
  canceled: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDeleteResponse {
  source_id: number;
  job: KnowledgeDeleteJob;
}
