import axios from 'axios';
import type { AnalyzeJDResponse, JDAnalysis } from '@/types/ai';

const http = axios.create({ baseURL: '/api', timeout: 130000 });

export async function analyzeJD(payload: {
  jd_text?: string;
  jd_url?: string;
  application_id?: number;
}): Promise<AnalyzeJDResponse> {
  const { data } = await http.post<AnalyzeJDResponse>('/jd/analyze', payload);
  return data;
}

export async function listJDAnalyses(applicationID?: number): Promise<JDAnalysis[]> {
  const { data } = await http.get<JDAnalysis[]>('/jd/analyses', {
    params: applicationID ? { application_id: applicationID } : undefined,
  });
  return data;
}