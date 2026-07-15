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
  source_provenance?: KnowledgeSourceProvenance;
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

export interface KnowledgeSourceProvenance {
  title?: string;
  author?: string;
  url?: string;
  published_at?: string;
  captured_at: string;
  metadata_extraction_version: string;
}

export interface KnowledgeEvidencePolicyRule {
  rule_id: string;
  label: string;
  count: number;
}

export interface KnowledgeEvidencePolicySummary {
  filtered_block_total: number;
  evidence_policy_version: string;
  rules: KnowledgeEvidencePolicyRule[];
}

export interface KnowledgeSource {
  id: number;
  source_kind: string;
  title: string;
  display_title: string;
  title_hint: string;
  author: string;
  published_at: string | null;
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
  provenance: KnowledgeSourceProvenance;
  evidence_policy_summary?: KnowledgeEvidencePolicySummary;
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
  next_retry_at: string | null;
  error_code: string;
  error_message: string;
  canceled: boolean;
  lease_owner: string;
  lease_expires_at: string | null;
  heartbeat_at: string | null;
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
  previous_evidence_id: string | null;
  next_evidence_id: string | null;
  source_provenance?: KnowledgeSourceProvenance;
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
  next_retry_at: string | null;
  error_code: string;
  error_message: string;
  canceled: boolean;
  lease_owner: string;
  lease_expires_at: string | null;
  heartbeat_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDeleteResponse {
  source_id: number;
  job: KnowledgeDeleteJob;
}

export interface BriefStatement {
  statement: string;
  evidence_ids: string[];
}

export interface BriefSectionGuide {
  section_key: string;
  heading_path: string[];
  summary: string;
  evidence_ids: string[];
}

export interface BriefCoverage {
  section_key: string;
  status: 'covered' | 'skipped';
  skipped_reason: string;
}

export interface BriefPayload {
  schema_version: number;
  language: string;
  overview: BriefStatement[];
  key_points: BriefStatement[];
  section_guides: BriefSectionGuide[];
  limitations: BriefStatement[];
  // KBR-04：coverage 由程序从实际 citations 派生并由 API 注入到 current Brief；
  // 候选 Brief（candidate_payload）未通过门禁，不带 coverage。
  coverage?: BriefCoverage[];
}

export interface KnowledgeSourceBrief {
  id: number;
  source_id: number;
  snapshot_id: number;
  winning_attempt_id: number;
  schema_version: number;
  language: string;
  payload: BriefPayload;
  outdated: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBriefAttempt {
  id: number;
  source_id: number;
  snapshot_id: number;
  status: string;
  provider_id: string;
  provider_model: string;
  context_window: number;
  max_output_tokens: number;
  prompt_version: string;
  schema_version: number;
  language: string;
  candidate_payload: BriefPayload | null;
  validation_report: Record<string, unknown>;
  error_code: string;
  error_message: string;
  repair_count: number;
  // KI-10：fallback 候选、实际成功 Provider、Provider 层重试进度。
  fallback_provider_id: string;
  fallback_provider_model: string;
  actual_provider_id: string;
  actual_provider_model: string;
  provider_retry_count: number;
  next_retry_at: string | null;
  token_input_count: number;
  token_output_count: number;
  latency_ms: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSourceBriefResponse {
  source_id: number;
  brief_status: string;
  brief_block_reason: string;
  brief_error_code: string;
  brief_error_message: string;
  brief: KnowledgeSourceBrief | null;
  latest_attempt: KnowledgeBriefAttempt | null;
  attempts: KnowledgeBriefAttempt[];
}

export interface KnowledgeBriefRebuildResponse {
  source_id: number;
  brief_status: string;
  brief_block_reason: string;
  brief_error_code: string;
  brief_error_message: string;
  status: string;
}
