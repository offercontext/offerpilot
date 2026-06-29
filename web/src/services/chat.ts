import axios from 'axios';
import type { ChatMessage, ChatResponse, Conversation } from '@/types/chat';

const http = axios.create({ baseURL: '/api', timeout: 130000 });

export async function sendChat(message: string, conversationId?: number): Promise<ChatResponse> {
  const { data } = await http.post<ChatResponse>('/chat', {
    message,
    conversation_id: conversationId ?? 0,
  });
  return data;
}

export async function confirmAction(conversationId: number, approved: boolean): Promise<ChatResponse> {
  const { data } = await http.post<ChatResponse>('/chat/confirm', {
    conversation_id: conversationId,
    approved,
  });
  return data;
}

export async function listConversations(): Promise<Conversation[]> {
  const { data } = await http.get<Conversation[]>('/chat/conversations');
  return data ?? [];
}

export async function getConversation(id: number): Promise<ChatMessage[]> {
  const { data } = await http.get<ChatMessage[]>(`/chat/conversations/${id}`);
  return data ?? [];
}

export async function deleteConversation(id: number): Promise<void> {
  await http.delete(`/chat/conversations/${id}`);
}

export interface Settings {
  chat_auto_approve_writes: boolean;
  model: string;
  has_api_key: boolean;
}

export async function getSettings(): Promise<Settings> {
  const { data } = await http.get<Settings>('/settings');
  return data;
}

export async function updateAutoApprove(value: boolean): Promise<Settings> {
  const { data } = await http.put<Settings>('/settings', { chat_auto_approve_writes: value });
  return data;
}
