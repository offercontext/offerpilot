import type { CreateResumeInput, Resume, MatchResumeResponse } from '@/types/resume';
import { createApiClient } from './http';

const http = createApiClient({ baseURL: '/api', timeout: 130000 });

export async function createResume(input: CreateResumeInput): Promise<Resume> {
  const { data } = await http.post<Resume>('/resumes', input);
  return data;
}

export async function listResumes(): Promise<Resume[]> {
  const { data } = await http.get<Resume[]>('/resumes');
  return data;
}

export async function deleteResume(id: number): Promise<void> {
  await http.delete(`/resumes/${id}`);
}

export async function matchResume(
  resumeID: number,
  payload: { jd_text?: string; jd_url?: string; application_id?: number },
): Promise<MatchResumeResponse> {
  const { data } = await http.post<MatchResumeResponse>(`/resumes/${resumeID}/match`, payload);
  return data;
}

export async function uploadResume(file: File): Promise<Resume> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await http.post<Resume>('/resumes/upload', formData, {
    timeout: 30000,
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function updateResumeText(id: number, text: string): Promise<void> {
  await http.put(`/resumes/${id}/text`, { text });
}

export async function downloadResumeFile(id: number): Promise<Blob> {
  const { data } = await http.get(`/resumes/${id}/file`, { responseType: 'blob' });
  return data;
}
