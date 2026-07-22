export type InterviewReviewSourceStatus = 'current' | 'source_changed';

export interface InterviewReviewEvidenceRef {
  source: 'interview_note';
  path: '/questions' | '/self_reflection' | '/difficulty_points' | '/mood';
  excerpt: string;
}

export interface InterviewReviewSummary {
  text: string;
  evidence_refs: InterviewReviewEvidenceRef[];
}

export interface InterviewReviewObservation {
  id: string;
  text: string;
  evidence_refs: InterviewReviewEvidenceRef[];
}

export interface InterviewReviewQuestion {
  id: string;
  question: string;
  evidence_refs: InterviewReviewEvidenceRef[];
}

export interface InterviewReviewPracticeFocus {
  id: string;
  text: string;
  evidence_refs: InterviewReviewEvidenceRef[];
}

export interface InterviewReviewProposalContent {
  summary: InterviewReviewSummary;
  observations: InterviewReviewObservation[];
  clarifications: InterviewReviewQuestion[];
  practice_focuses: InterviewReviewPracticeFocus[];
  next_questions: InterviewReviewQuestion[];
}

export interface InterviewReviewProposal {
  id: number;
  note_id: number;
  application_event_id?: number | null;
  source_fingerprint: string;
  source_status: InterviewReviewSourceStatus;
  proposal: InterviewReviewProposalContent;
  proposal_hash: string;
  created_at: string;
}
