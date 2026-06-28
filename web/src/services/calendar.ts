import axios from 'axios';
import type { CalendarEntry } from '@/types/calendar';

const http = axios.create({ baseURL: '/api', timeout: 10000 });

// month param format: "YYYY-MM"
export async function getCalendar(month: string): Promise<CalendarEntry[]> {
  const { data } = await http.get<CalendarEntry[]>('/calendar', { params: { month } });
  return data;
}