import type { ChatMessage, ChatResponse, Conversation } from '@/types/chat';
import { createApiClient } from './http';

const http = createApiClient({ baseURL: '/api', timeout: 130000 });
export const SETTINGS_QUERY_KEY = ['settings'] as const;

export interface ChatContextInput {
  context_type?: 'workspace' | 'application' | 'global' | string;
  context_ref?: string | number;
  mode?: string;
}

export async function sendChat(
  message: string,
  conversationId?: number,
  context?: ChatContextInput,
): Promise<ChatResponse> {
  const { data } = await http.post<ChatResponse>('/chat', {
    message,
    conversation_id: conversationId ?? 0,
    ...(context?.context_type ? { context_type: context.context_type } : {}),
    ...(context?.context_ref !== undefined ? { context_ref: String(context.context_ref) } : {}),
    ...(context?.mode ? { mode: context.mode } : {}),
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
  fallback_provider_ids: string[];
  providers: AIProviderProfile[];
  base_url: string;
  model: string;
  has_api_key: boolean;
  runtime_mode: 'local' | 'server';
  auth_enabled: boolean;
  has_auth_token: boolean;
  log_level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
}

export interface LogEntry {
  level: string;
  message: string;
}

export interface LogsResponse {
  entries: LogEntry[];
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
  fallback_provider_ids?: string[];
  providers?: Array<Omit<AIProviderProfile, 'has_api_key'> & { api_key?: string }>;
  base_url?: string;
  model?: string;
  api_key?: string;
}

export interface ProviderTestPayload {
  provider_id?: string;
  provider?: Omit<AIProviderProfile, 'has_api_key'> & { api_key?: string };
}

export interface ProviderTestResult {
  ok: boolean;
  provider_id: string;
  error: string;
  latency_ms: number;
}

export async function getSettings(): Promise<Settings> {
  const { data } = await http.get<Settings>('/settings');
  return data;
}

export async function updateSettings(payload: UpdateSettingsPayload): Promise<Settings> {
  const { data } = await http.put<Settings>('/settings', payload);
  return data;
}

export async function testProviderConnection(payload: ProviderTestPayload): Promise<ProviderTestResult> {
  const { data } = await http.post<ProviderTestResult>('/settings/providers/test', payload);
  return data;
}

export function exportBackup(path = '/backups/export'): void {
  window.location.href = `/api${path}`;
}

export async function getLogs(limit = 20): Promise<LogEntry[]> {
  const { data } = await http.get<LogsResponse>('/logs', { params: { limit } });
  return data.entries ?? [];
}

export async function updateAutoApprove(value: boolean): Promise<Settings> {
  const current = await getSettings();
  return updateSettings({
    chat_auto_approve_writes: value,
    base_url: current.base_url,
    model: current.model,
  });
}
