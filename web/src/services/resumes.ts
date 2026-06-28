import axios from 'axios';
import type { CreateResumeInput, Resume, MatchResumeResponse } from '@/types/resume';

const http = axios.create({ baseURL: '/api', timeout: 130000 });

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