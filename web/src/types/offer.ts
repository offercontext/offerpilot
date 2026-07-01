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
