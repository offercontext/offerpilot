export type OpportunityFitRecommendation = 'advance' | 'hold' | 'decline';

export interface OpportunityFitEvidenceRef {
  source: 'jd' | 'resume' | 'user_assertion';
  path: string;
  excerpt: string;
}

export interface OpportunityFitTriage {
  summary: string;
  recommendation: OpportunityFitRecommendation;
  hard_constraints: Array<{
    id: string;
    requirement: string;
    status: 'met' | 'unmet' | 'unknown';
    explanation: string;
    evidence_refs: OpportunityFitEvidenceRef[];
  }>;
  fit_signals: Array<{
    id: string;
    statement: string;
    evidence_refs: OpportunityFitEvidenceRef[];
  }>;
  gaps: Array<{
    id: string;
    requirement: string;
    kind: 'required' | 'preferred';
    candidate_status: 'met' | 'unmet' | 'unknown';
    evidence_refs: OpportunityFitEvidenceRef[];
  }>;
  deadline: {
    status: 'stated' | 'not_stated';
    text: string;
    evidence_refs: OpportunityFitEvidenceRef[];
  };
  next_questions: string[];
}

export interface OpportunityFitDeepReview {
  strengths: Array<{ id: string; statement: string; evidence_refs: OpportunityFitEvidenceRef[] }>;
  gaps_to_address: Array<{ id: string; statement: string; evidence_refs: OpportunityFitEvidenceRef[] }>;
  questions_to_clarify: Array<{ id: string; statement: string; evidence_refs: OpportunityFitEvidenceRef[] }>;
  recommended_path: 'prepare_materials' | 'clarify_first' | 'do_not_pursue';
  next_actions: Array<{ id: string; label: string; kind: 'open_material_kit' | 'add_assertion' | 'record_deadline' }>;
}

export interface OpportunityFitSource {
  application: { id: number; company_name: string; position_name: string };
  resume: { id: number; title: string; sha256: string };
  jd: { source_label: string; sha256: string; text: string };
  candidate_assertions: Array<{ index: number; text: string }>;
}

export interface OpportunityFitReviewSummary {
  id: number;
  application_id: number;
  resume_id: number | null;
  status: 'triage_complete' | 'deep_reviewed';
  summary: string;
  recommendation: OpportunityFitRecommendation;
  source_fingerprint_sha256: string;
  triage_sha256: string;
  deep_review_sha256: string | null;
  created_at: string;
  deep_reviewed_at: string | null;
}

export interface OpportunityFitReview extends OpportunityFitReviewSummary {
  source: OpportunityFitSource;
  triage: OpportunityFitTriage;
  deep_review: OpportunityFitDeepReview | null;
}

export interface CreateOpportunityFitReviewInput {
  resume_id: number;
  jd_text: string;
  jd_source_label: string;
  candidate_assertions: string[];
  idempotency_key: string;
}
