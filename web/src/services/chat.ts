import axios from 'axios';
import type { ChatMessage, ChatResponse, Conversation } from '@/types/chat';

const http = axios.create({ baseURL: '/api', timeout: 130000 });
export const SETTINGS_QUERY_KEY = ['settings'] as const;

export async function sendChat(
  message: string,
  conversationId?: number,
  offerId?: number,
): Promise<ChatResponse> {
  const { data } = await http.post<ChatResponse>('/chat', {
    message,
    conversation_id: conversationId ?? 0,
    ...(offerId ? { offer_id: offerId } : {}),
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
  active_provider_id: string;
  providers: AIProviderProfile[];
  base_url: string;
  model: string;
  has_api_key: boolean;
}

export interface AIProviderProfile {
  id: string;
  label: string;
  provider: string;
  base_url: string;
  model: string;
  enabled: boolean;
  has_api_key: boolean;
}

export interface UpdateSettingsPayload {
  chat_auto_approve_writes: boolean;
  active_provider_id?: string;
  providers?: Array<Omit<AIProviderProfile, 'has_api_key'> & { api_key?: string }>;
  base_url: string;
  model: string;
  api_key?: string;
}

export async function getSettings(): Promise<Settings> {
  const { data } = await http.get<Settings>('/settings');
  return data;
}

export async function updateSettings(payload: UpdateSettingsPayload): Promise<Settings> {
  const { data } = await http.put<Settings>('/settings', payload);
  return data;
}

export async function updateAutoApprove(value: boolean): Promise<Settings> {
  const current = await getSettings();
  return updateSettings({
    chat_auto_approve_writes: value,
    base_url: current.base_url,
    model: current.model,
  });
}
