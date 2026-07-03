export interface MockSession {
  id: number;
  conversation_id: number;
  application_id?: number;
  title: string;
  role: string;
  company: string;
  round_type: string; // technical | behavioral | coding | hr | mixed
  difficulty: string; // easy | medium | hard
  question_count: number; // 0 = unlimited
  duration_min: number; // 0 = unlimited
  question_source: string; // bank | knowledge | notes | mixed
  knowledge_base_id?: number;
  status: string; // in_progress | completed | aborted
  question_index: number;
  started_at: string;
  ended_at?: string;
  score_overall?: number;
  score_communication?: number;
  score_depth?: number;
  score_structure?: number;
  score_confidence?: number;
  feedback?: string; // JSON string of MockFeedback
  created_at: string;
}

export interface MockConfig {
  application_id?: number;
  title?: string;
  role: string;
  company?: string;
  round_type?: string;
  difficulty?: string;
  question_count?: number;
  duration_min?: number;
  question_source?: string;
  knowledge_base_id?: number;
}

export interface MockDrill {
  area: string;
  action: string;
  link_question_ids?: number[];
}

export interface MockFeedback {
  score_overall: number;
  score_communication: number;
  score_depth: number;
  score_structure: number;
  score_confidence: number;
  summary: string;
  strengths: string[];
  weaknesses: string[];
  drills: MockDrill[];
}

export interface MockSessionCreateResponse {
  session: MockSession;
  conversation_id: number;
  conversation: { id: number; title: string; mode: string };
}

export interface MockSessionDetailResponse {
  session: MockSession;
  messages: import('@/types/chat').ChatMessage[];
}

export interface MockEndResponse {
  session: MockSession;
  feedback: MockFeedback;
  parse_error: boolean;
  saved_note_id?: number;
}