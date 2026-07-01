import axios from 'axios';
import type {
  KnowledgeBase,
  KnowledgeBaseInput,
  KnowledgeDocument,
  KnowledgeDocumentInput,
  KnowledgeSearchResult,
} from '@/types/knowledge';

const http = axios.create({ baseURL: '/api', timeout: 10000 });

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const { data } = await http.get<KnowledgeBase[]>('/knowledge-bases');
  return data;
}

export async function createKnowledgeBase(input: KnowledgeBaseInput): Promise<KnowledgeBase> {
  const { data } = await http.post<KnowledgeBase>('/knowledge-bases', input);
  return data;
}

export async function updateKnowledgeBase(id: number, input: KnowledgeBaseInput): Promise<KnowledgeBase> {
  const { data } = await http.put<KnowledgeBase>(`/knowledge-bases/${id}`, input);
  return data;
}

export async function deleteKnowledgeBase(id: number): Promise<void> {
  await http.delete(`/knowledge-bases/${id}`);
}

export async function listKnowledgeDocuments(
  knowledgeBaseId?: number,
  q?: string,
): Promise<KnowledgeDocument[]> {
  const { data } = await http.get<KnowledgeDocument[]>('/knowledge-documents', {
    params: {
      ...(knowledgeBaseId ? { knowledge_base_id: knowledgeBaseId } : {}),
      ...(q ? { q } : {}),
    },
  });
  return data;
}

export async function getKnowledgeDocument(id: number): Promise<KnowledgeDocument> {
  const { data } = await http.get<KnowledgeDocument>(`/knowledge-documents/${id}`);
  return data;
}

export async function createKnowledgeDocument(input: KnowledgeDocumentInput): Promise<KnowledgeDocument> {
  const { data } = await http.post<KnowledgeDocument>('/knowledge-documents', input);
  return data;
}

export async function updateKnowledgeDocument(
  id: number,
  input: KnowledgeDocumentInput,
): Promise<KnowledgeDocument> {
  const { data } = await http.put<KnowledgeDocument>(`/knowledge-documents/${id}`, input);
  return data;
}

export async function deleteKnowledgeDocument(id: number): Promise<void> {
  await http.delete(`/knowledge-documents/${id}`);
}

export async function importKnowledgeDocument(
  knowledgeBaseId: number,
  file: File,
): Promise<KnowledgeDocument> {
  const formData = new FormData();
  formData.append('knowledge_base_id', String(knowledgeBaseId));
  formData.append('file', file);

  const { data } = await http.post<KnowledgeDocument>('/knowledge-documents/import', formData);
  return data;
}

export async function searchKnowledge(
  q: string,
  knowledgeBaseId?: number,
): Promise<KnowledgeSearchResult[]> {
  const { data } = await http.get<KnowledgeSearchResult[]>('/knowledge/search', {
    params: {
      q,
      ...(knowledgeBaseId ? { knowledge_base_id: knowledgeBaseId } : {}),
    },
  });
  return data;
}
