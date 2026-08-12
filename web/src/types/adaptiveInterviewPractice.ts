export type AdaptivePracticeDrillKind =
  | 'difficulty_breakdown'
  | 'answer_reframe'
  | 'question_decode'
  | 'pressure_rehearsal';

export type AdaptivePracticeSourceStatus = 'current' | 'changed' | 'missing';
export type AdaptivePracticeAssessment = 'needs_work' | 'clearer' | 'confident';

export interface AdaptivePracticeRecommendation {
  proposal_id: number;
  focus_id: string;
  application_id: number;
  application_event_id: number;
  interview_note_id: number;
  company_name: string;
  position_name: string;
  drill_kind: AdaptivePracticeDrillKind;
  title: string;
  observation: string;
  reason: string;
  prompt: string;
  source_path: string;
  source_excerpt: string;
  source_fingerprint: string;
}

export interface AdaptivePracticePlan extends AdaptivePracticeRecommendation {
  id: number;
  status: 'in_progress' | 'completed';
  revision: number;
  source_status: AdaptivePracticeSourceStatus;
  response_text: string;
  reflection_text: string;
  self_assessment: AdaptivePracticeAssessment | '';
  created_at: string;
  completed_at: string | null;
}

export interface AdaptivePracticeFocus {
  proposalId: number;
  focusId: string;
}

export interface AdaptivePracticeCompleteInput {
  expected_revision: number;
  response_text: string;
  reflection_text: string;
  self_assessment: AdaptivePracticeAssessment;
  idempotency_key: string;
}
