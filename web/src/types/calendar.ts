// Mirrors Go api.CalendarEntry JSON tags.
export type CalendarEntryType = 'interview' | 'applied';

export interface CalendarEntry {
  date: string;        // YYYY-MM-DD
  type: CalendarEntryType;
  title: string;
  subtitle?: string;
  app_id: number;
  note_id?: number;
}