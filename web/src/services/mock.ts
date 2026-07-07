import type {
  MockSession,
  MockSessionCreateResponse,
  MockSessionDetailResponse,
  MockEndResponse,
  MockConfig,
} from '@/types/mock';
import { createApiClient } from './http';

const http = createApiClient({ baseURL: '/api/mock', timeout: 180000 });

export async function listMockSessions(status?: string): Promise<MockSession[]> {
  const { data } = await http.get<MockSession[]>('/sessions', {
    params: status ? { status } : {},
  });
  return data ?? [];
}

export async function getMockSession(id: number): Promise<MockSessionDetailResponse> {
  const { data } = await http.get<MockSessionDetailResponse>(`/sessions/${id}`);
  return data;
}

export async function createMockSession(config: MockConfig): Promise<MockSessionCreateResponse> {
  const { data } = await http.post<MockSessionCreateResponse>('/sessions', config);
  return data;
}

export async function endMockSession(id: number, autoSaveNote = false): Promise<MockEndResponse> {
  const { data } = await http.post<MockEndResponse>(`/sessions/${id}/end`, {
    auto_save_note: autoSaveNote,
  });
  return data;
}

export async function deleteMockSession(id: number): Promise<void> {
  await http.delete(`/sessions/${id}`);
}
