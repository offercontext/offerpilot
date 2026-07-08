export interface KnowledgeDocument {
  id: number;
  title: string;
  content: string;
  tags: string[];
  doc_kind: 'wiki' | 'ai_summary' | string;
  status: 'confirmed' | 'pending' | 'rejected' | string;
  source_type: 'manual' | 'markdown' | 'paste' | 'upload' | string;
  source_name: string;
  source_refs: string;
  summary_type: string;
  generation_meta: string;
  superseded_by?: number | null;
  confirmed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSearchResult {
  document_id: number;
  document_title: string;
  chunk_id: number;
  snippet: string;
  score: number;
}

export interface KnowledgeDocumentInput {
  title: string;
  content: string;
  tags?: string[];
}
