import type { MatchResult } from './ai';

// Resume row — mirrors Go db.Resume JSON tags.
export interface Resume {
  id: number;
  name: string;
  file_path: string;
  parsed_data: string;
  parse_status: string;
  created_at: string;
}

export interface CreateResumeInput {
  name?: string;
  text: string;
}

export interface MatchResumeResponse {
  id: number;
  resume_id: number;
  application_id?: number;
  result: MatchResult;
}

export type ResumeStatus = 'text-ready' | 'parse-failed';