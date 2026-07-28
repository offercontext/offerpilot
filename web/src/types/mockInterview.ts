export interface MockInterviewTurn {
  turn_no: number;
  question: string;
  answer: string;
}

export interface MockInterviewProposal {
  schema_version: string;
  proposal_status: 'normal' | 'safe_empty';
  strengths: MockInterviewFeedbackBlock[];
  practice_points: MockInterviewFeedbackBlock[];
  follow_up_questions: MockInterviewFeedbackBlock[];
  next_practice_steps: MockInterviewFeedbackBlock[];
}

export interface MockInterviewFeedbackBlock {
  id: string;
  text: string;
  evidence_refs: Array<{ source: string; path: string; excerpt: string }>;
}

export interface MockInterviewAttemptResponse {
  attempt_id: number;
  attempt_status: string;
  generation_revision: number;
  turn: MockInterviewTurn;
}

export interface MockInterviewProposalResponse {
  proposal_id: number;
  proposal_status: 'normal' | 'safe_empty';
  proposal_hash: string;
  proposal: MockInterviewProposal;
}

export interface MockInterviewHistoryItem extends MockInterviewProposalResponse {
  attempt_id: number;
  source_fingerprint: string;
  transcript_fingerprint: string;
  created_at: string;
}

