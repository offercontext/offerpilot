import type {
  KnowledgeDocument,
  KnowledgeDocumentInput,
  KnowledgeSearchResult,
} from '@/types/knowledge';
import { createApiClient } from './http';

const http = createApiClient({ baseURL: '/api', timeout: 10000 });

export async function listKnowledgeDocuments(q?: string): Promise<KnowledgeDocument[]> {
  const { data } = await http.get<KnowledgeDocument[]>('/knowledge-documents', {
    params: {
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

export async function importKnowledgeDocument(file: File): Promise<KnowledgeDocument> {
  const formData = new FormData();
  formData.append('file', file);

  const { data } = await http.post<KnowledgeDocument>('/knowledge-documents/import', formData);
  return data;
}

export async function searchKnowledge(q: string): Promise<KnowledgeSearchResult[]> {
  const { data } = await http.get<KnowledgeSearchResult[]>('/knowledge/search', {
    params: { q },
  });
  return data;
}
