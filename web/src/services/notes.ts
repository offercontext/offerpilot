import axios from 'axios';
import type { CreateNoteInput, InterviewNote } from '@/types/note';

const http = axios.create({ baseURL: '/api', timeout: 10000 });

export async function listNotesByApp(appID: number): Promise<InterviewNote[]> {
  const { data } = await http.get<InterviewNote[]>(`/applications/${appID}/notes`);
  return data;
}

export async function createNote(appID: number, input: CreateNoteInput): Promise<InterviewNote> {
  const { data } = await http.post<InterviewNote>(`/applications/${appID}/notes`, input);
  return data;
}

export async function deleteNote(id: number): Promise<void> {
  await http.delete(`/notes/${id}`);
}