export interface InterviewIndexItem {
  application_id: number;
  event_id: number;
  company_name: string;
  position_name: string;
  scheduled_at: string;
  note_id: number | null;
  note_source_status: 'current' | 'source_changed' | null;
  has_review_proposal: boolean;
  has_confirmed_knowledge: boolean;
  preparation_available: boolean;
}

export interface InterviewIndexResponse {
  items: InterviewIndexItem[];
  next_cursor: string | null;
}
