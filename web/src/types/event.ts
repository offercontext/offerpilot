export type ScheduleEventType = 'written_test' | 'interview' | 'assessment';

export const EVENT_TYPE_LABELS: Record<ScheduleEventType, string> = {
  written_test: '笔试',
  interview: '面试',
  assessment: '测评',
};

export interface ScheduleEvent {
  id: number;
  application_id: number;
  event_type: ScheduleEventType;
  round: number;
  scheduled_at: string;
  duration_minutes: number;
  location: string;
  notes: string;
  company_name?: string;
  position_name?: string;
  created_at: string;
}

export interface ScheduleEventInput {
  application_id: number;
  event_type: ScheduleEventType;
  round?: number;
  scheduled_at: string;
  duration_minutes: number;
  location?: string;
  notes?: string;
}
