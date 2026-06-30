import axios from 'axios';
import type { ScheduleEvent, ScheduleEventInput, ScheduleEventType } from '@/types/event';

const http = axios.create({
  baseURL: '/api',
  timeout: 10000,
});

interface ListEventsParams {
  month?: string;
  application_id?: number;
  type?: ScheduleEventType;
}

export async function listEvents(params?: ListEventsParams): Promise<ScheduleEvent[]> {
  const { data } = await http.get<ScheduleEvent[]>('/events', { params });
  return data;
}

export async function getEvent(id: number): Promise<ScheduleEvent> {
  const { data } = await http.get<ScheduleEvent>(`/events/${id}`);
  return data;
}

export async function createEvent(input: ScheduleEventInput): Promise<ScheduleEvent> {
  const { data } = await http.post<ScheduleEvent>('/events', input);
  return data;
}

export async function updateEvent(
  id: number,
  input: ScheduleEventInput
): Promise<ScheduleEvent> {
  const { data } = await http.put<ScheduleEvent>(`/events/${id}`, input);
  return data;
}

export async function deleteEvent(id: number): Promise<void> {
  await http.delete(`/events/${id}`);
}
