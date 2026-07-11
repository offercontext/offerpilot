import { createContext, useContext, useMemo, useReducer, useRef, type ReactNode } from 'react';
import {
  addPilotAttachment,
  emptyPilotAttachmentDraft,
  removePilotAttachment,
  type PilotAttachmentDraft,
} from '@/lib/pilotAttachments';
import type { PilotContextAttachment } from '@/types/chat';

export type PilotAttachmentConversationKey = `conversation:${number}` | `new:${string}`;

export interface PilotAttachmentState {
  activeKey?: PilotAttachmentConversationKey;
  drafts: Partial<Record<PilotAttachmentConversationKey, PilotAttachmentDraft>>;
}

type PilotAttachmentAction =
  | { type: 'set-active'; key?: PilotAttachmentConversationKey }
  | { type: 'add'; attachment: PilotContextAttachment }
  | { type: 'remove'; attachmentOrKey: PilotContextAttachment | string }
  | { type: 'clear-active' }
  | { type: 'clear-by-key'; key: PilotAttachmentConversationKey };

export interface PilotAttachmentContextValue {
  attachments: PilotContextAttachment[];
  notice?: string;
  setActiveConversationKey: (key?: PilotAttachmentConversationKey) => void;
  addAttachment: (attachment: PilotContextAttachment) => void;
  removeAttachment: (attachmentOrKey: PilotContextAttachment | string) => void;
  clearAttachments: () => void;
  clearAttachmentsByKey: (key: PilotAttachmentConversationKey) => void;
  beginNewAttachmentDraft: () => PilotAttachmentConversationKey;
  ensureNewAttachmentDraft: () => PilotAttachmentConversationKey;
}

const PilotAttachmentContext = createContext<PilotAttachmentContextValue | null>(null);

export function emptyPilotAttachmentState(): PilotAttachmentState {
  return { drafts: {} };
}

function withDraft(
  state: PilotAttachmentState,
  key: PilotAttachmentConversationKey,
  draft: PilotAttachmentDraft,
): PilotAttachmentState {
  return { ...state, drafts: { ...state.drafts, [key]: draft } };
}

export function pilotAttachmentStateReducer(
  state: PilotAttachmentState,
  action: PilotAttachmentAction,
): PilotAttachmentState {
  switch (action.type) {
    case 'set-active':
      return state.activeKey === action.key ? state : { ...state, activeKey: action.key };
    case 'add': {
      if (!state.activeKey) return state;
      return withDraft(
        state,
        state.activeKey,
        addPilotAttachment(state.drafts[state.activeKey] ?? emptyPilotAttachmentDraft(), action.attachment),
      );
    }
    case 'remove': {
      if (!state.activeKey) return state;
      return withDraft(
        state,
        state.activeKey,
        removePilotAttachment(
          state.drafts[state.activeKey] ?? emptyPilotAttachmentDraft(),
          action.attachmentOrKey,
        ),
      );
    }
    case 'clear-active':
      return state.activeKey
        ? withDraft(state, state.activeKey, emptyPilotAttachmentDraft())
        : state;
    case 'clear-by-key':
      return withDraft(state, action.key, emptyPilotAttachmentDraft());
  }
}

export function PilotAttachmentProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(pilotAttachmentStateReducer, undefined, emptyPilotAttachmentState);
  const nextNewDraftKeyRef = useRef(0);
  const activeDraft = state.activeKey
    ? state.drafts[state.activeKey] ?? emptyPilotAttachmentDraft()
    : emptyPilotAttachmentDraft();
  const value = useMemo<PilotAttachmentContextValue>(
    () => ({
      attachments: activeDraft.attachments,
      notice: activeDraft.message,
      setActiveConversationKey: (key) => dispatch({ type: 'set-active', key }),
      addAttachment: (attachment) => dispatch({ type: 'add', attachment }),
      removeAttachment: (attachmentOrKey) => dispatch({ type: 'remove', attachmentOrKey }),
      clearAttachments: () => dispatch({ type: 'clear-active' }),
      clearAttachmentsByKey: (key) => dispatch({ type: 'clear-by-key', key }),
      beginNewAttachmentDraft: () => {
        const key = `new:draft-${++nextNewDraftKeyRef.current}` as PilotAttachmentConversationKey;
        dispatch({ type: 'set-active', key });
        return key;
      },
      ensureNewAttachmentDraft: () => {
        if (state.activeKey?.startsWith('new:')) return state.activeKey;
        const key = `new:draft-${++nextNewDraftKeyRef.current}` as PilotAttachmentConversationKey;
        dispatch({ type: 'set-active', key });
        return key;
      },
    }),
    [activeDraft.attachments, activeDraft.message, state.activeKey],
  );

  return <PilotAttachmentContext.Provider value={value}>{children}</PilotAttachmentContext.Provider>;
}

export function usePilotAttachments(): PilotAttachmentContextValue {
  const value = useContext(PilotAttachmentContext);
  if (!value) throw new Error('usePilotAttachments must be used within PilotAttachmentProvider');
  return value;
}
