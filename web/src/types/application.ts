// Application status lifecycle. Mirrors the Go db.Application.Status values.
export type ApplicationStatus =
  | 'applied'
  | 'assessment'
  | 'written_test'
  | 'interview'
  | 'offer'
  | 'eliminated'
  | 'rejected';

// Application record — fields match the Go JSON tags (snake_case).
export interface Application {
  id: number;
  company_name: string;
  position_name: string;
  job_url: string;
  status: ApplicationStatus;
  source: string;
  notes: string;
  applied_at: string;
  created_at: string;
  updated_at: string;
}

// Payload for creating/updating an application.
export interface ApplicationInput {
  company_name: string;
  position_name: string;
  job_url?: string;
  status?: ApplicationStatus;
  notes?: string;
}

export interface DashboardSummary {
  total: number;
  board: Record<string, Application[]>;
}

// Column definitions for the kanban board, in lifecycle order.
export const STATUS_LABELS: Record<ApplicationStatus, string> = {
  applied: '已投递',
  assessment: '测评',
  written_test: '笔试',
  interview: '面试',
  offer: 'Offer',
  eliminated: '挂了',
  rejected: '被拒',
};

export const STATUS_COLORS: Record<ApplicationStatus, string> = {
  applied: '#0284c7',
  assessment: '#7c3aed',
  written_test: '#ea580c',
  interview: '#059669',
  offer: '#16a34a',
  eliminated: '#94a3b8',
  rejected: '#dc2626',
};

export const KANBAN_COLUMNS: ApplicationStatus[] = [
  'applied',
  'assessment',
  'written_test',
  'interview',
  'offer',
  'eliminated',
  'rejected',
];
