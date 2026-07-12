import type {
  KnowledgeEvidence,
  KnowledgeEvidencePage,
  KnowledgeEvidenceSearchResponse,
  KnowledgeIngestResponse,
  KnowledgeSource,
  KnowledgeSourceJobsResponse,
} from '@/types/knowledge';
import { createApiClient } from './http';

const http = createApiClient({ baseURL: '/api', timeout: 30000 });

export async function fetchKnowledgeSources(): Promise<KnowledgeSource[]> {
  const { data } = await http.get<KnowledgeSource[]>('/knowledge/sources');
  return data;
}

export async function fetchKnowledgeSource(sourceId: number): Promise<KnowledgeSource> {
  const { data } = await http.get<KnowledgeSource>(`/knowledge/sources/${sourceId}`);
  return data;
}

export async function fetchKnowledgeSourceEvidence(
  sourceId: number,
  params?: { after_ordinal?: number; limit?: number },
): Promise<KnowledgeEvidencePage> {
  const { data } = await http.get<KnowledgeEvidencePage>(
    `/knowledge/sources/${sourceId}/evidence`,
    { params },
  );
  return data;
}

export async function fetchKnowledgeSourceJobs(
  sourceId: number,
): Promise<KnowledgeSourceJobsResponse> {
  const { data } = await http.get<KnowledgeSourceJobsResponse>(
    `/knowledge/sources/${sourceId}/jobs`,
  );
  return data;
}

export async function fetchKnowledgeEvidence(evidenceId: string): Promise<KnowledgeEvidence> {
  const { data } = await http.get<KnowledgeEvidence>(`/knowledge/evidence/${evidenceId}`);
  return data;
}

export async function searchKnowledgeEvidence(
  query: string,
  options: { source_ids?: number[]; include_archived?: boolean; limit?: number } = {},
): Promise<KnowledgeEvidenceSearchResponse> {
  const { data } = await http.post<KnowledgeEvidenceSearchResponse>(
    '/knowledge/evidence/search',
    {
      query,
      source_ids: options.source_ids,
      include_archived: options.include_archived,
      limit: options.limit,
    },
  );
  return data;
}

export async function uploadKnowledgeSource(
  file: File,
  titleHint = '',
): Promise<KnowledgeIngestResponse> {
  const form = new FormData();
  form.append('file', file);
  if (titleHint) {
    form.append('title_hint', titleHint);
  }
  const { data } = await http.post<KnowledgeIngestResponse>('/knowledge/sources', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function pasteKnowledgeSource(
  paste: string,
  options: { titleHint?: string; originUrl?: string } = {},
): Promise<KnowledgeIngestResponse> {
  const form = new FormData();
  form.append('paste', paste);
  if (options.titleHint) {
    form.append('title_hint', options.titleHint);
  }
  if (options.originUrl) {
    form.append('origin_url', options.originUrl);
  }
  const { data } = await http.post<KnowledgeIngestResponse>('/knowledge/sources', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export function buildKnowledgeSourceContentUrl(sourceId: number): string {
  return `/api/knowledge/sources/${sourceId}/content`;
}
