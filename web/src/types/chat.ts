export interface Conversation {
  id: number;
  title: string;
  mode?: string;
  context_type: string;
  context_ref: string;
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
  target?: PendingActionTarget;
  proposed_changes?: PendingActionChange[];
  evidence?: PendingActionEvidence[];
}

export interface PendingActionTarget {
  id: string;
  kind: string;
  title: string;
  meta?: string;
  snippet?: string;
  source: string;
}

export interface PendingActionChange {
  field: string;
  before?: string | number | boolean | null;
  after?: string | number | boolean | null;
}

export interface PendingActionEvidence extends PendingActionTarget {}

export type ChatResponse =
  | { type: 'message'; conversation_id: number; message: string; degraded?: boolean }
  | { type: 'confirmation_required'; conversation_id: number; pending_action: PendingAction };
