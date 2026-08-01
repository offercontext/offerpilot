// Offer record — fields match the Go db.Offer JSON tags (snake_case).
export type OfferStatus = 'pending' | 'negotiating' | 'accepted' | 'declined' | 'expired';

export interface Offer {
  id: number;
  application_id?: number;
  company_name: string;
  position_name: string;
  status: OfferStatus;
  base_monthly: number;
  months_per_year: number;
  signing_bonus: number;
  equity: string;
  perks: string;
  deadline: string;
  notes: string;
  assessment: string;
  total_cash: number;
  created_at: string;
  updated_at: string;
}

export interface OfferInput {
  application_id?: number;
  company_name: string;
  position_name: string;
  status?: OfferStatus;
  base_monthly?: number;
  months_per_year?: number;
  signing_bonus?: number;
  equity?: string;
  perks?: string;
  deadline?: string;
  notes?: string;
  assessment?: string;
}

export interface OfferComparisonDimension {
  id: number;
  label: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OfferComparisonValue {
  id: number;
  offer_id: number;
  dimension_id: number;
  value_text: string | null;
  created_at: string;
  updated_at: string;
}

export interface OfferComparisonValueCell {
  offer_id: number;
  value_text: string | null;
}

export interface OfferComparisonDimensionRead {
  id: number;
  label: string;
  values: OfferComparisonValueCell[];
}

export interface OfferComparisonMissing {
  offer_id: number;
  path: string;
  label: string;
}

export interface OfferComparisonRead {
  offers: Offer[];
  dimensions: OfferComparisonDimensionRead[];
  missing: OfferComparisonMissing[];
}

export type OfferNegotiationProposalStatus = 'normal' | 'safe_empty';

export interface OfferNegotiationEvidenceRef {
  source: 'offer_snapshot' | 'user_brief';
  path: string;
  excerpt: string;
}

export interface OfferNegotiationBlock {
  id: string;
  text: string;
  rationale: string;
  evidence_refs: OfferNegotiationEvidenceRef[];
}

export interface OfferNegotiationProposal {
  id: number;
  offer_id: number;
  application_id?: number | null;
  attempt_status: 'ready';
  proposal_status: OfferNegotiationProposalStatus;
  proposal: {
    proposal_status: OfferNegotiationProposalStatus;
    communication_goals: OfferNegotiationBlock[];
    clarification_questions: OfferNegotiationBlock[];
    talking_points: OfferNegotiationBlock[];
    preparation_checks: OfferNegotiationBlock[];
  };
  source_fingerprint: string;
  source_changed: boolean;
  source_states: Record<string, string>;
  proposal_hash: string | null;
  brief?: OfferNegotiationBrief;
}

export interface OfferNegotiationPending {
  id: number;
  offer_id: number;
  application_id?: number | null;
  attempt_status: 'generating' | 'provider_unknown';
  retry_after_ms: number;
}

export interface OfferNegotiationBrief {
  id: number;
  proposal_id: number;
  offer_id: number;
  application_id?: number | null;
  selected_blocks: string[];
  edited_content: { blocks: OfferNegotiationBlock[]; edits: Record<string, string>; proposal_hash: string | null };
  content_hash: string;
  confirmed_at: string;
}

export class OfferNegotiationError extends Error {
  constructor(public status: number, public code: string | null) {
    super(code ?? 'offer_negotiation_error');
  }
}

export const OFFER_STATUS_LABELS: Record<OfferStatus, string> = {
  pending: '待处理',
  negotiating: '谈判中',
  accepted: '已接受',
  declined: '已拒绝',
  expired: '已过期',
};

export const OFFER_STATUS_COLORS: Record<OfferStatus, string> = {
  pending: '#0284c7',
  negotiating: '#d97706',
  accepted: '#16a34a',
  declined: '#94a3b8',
  expired: '#dc2626',
};
