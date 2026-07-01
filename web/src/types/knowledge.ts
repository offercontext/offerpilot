export interface KnowledgeBase {
  id: number;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: number;
  knowledge_base_id: number;
  title: string;
  content: string;
  tags: string[];
  source_type: 'manual' | 'upload';
  source_name: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSearchResult {
  knowledge_base_id: number;
  knowledge_base_name: string;
  document_id: number;
  document_title: string;
  chunk_id: number;
  snippet: string;
  score: number;
}

export interface KnowledgeBaseInput {
  name: string;
  description?: string;
}

export interface KnowledgeDocumentInput {
  knowledge_base_id: number;
  title: string;
  content: string;
  tags?: string[];
}
