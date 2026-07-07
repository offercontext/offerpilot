export interface Conversation {
  id: number;
  title: string;
  offer_id?: number;
  mode?: string;
  pending_action?: PendingAction | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  tool_calls?: string;
  tool_call_id?: string;
  created_at: string;
}

export interface PendingAction {
  tool_name: string;
  human: string;
  args?: Record<string, unknown>;
}

export type ChatResponse =
  | { type: 'message'; conversation_id: number; message: string; degraded?: boolean }
  | { type: 'confirmation_required'; conversation_id: number; pending_action: PendingAction };
