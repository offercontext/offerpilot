import { describe, expect, it } from 'vitest';
import {
  captureActiveAttachmentKey,
  emptyPilotAttachmentState,
  pilotAttachmentStateReducer,
  type PilotAttachmentState,
} from './PilotAttachmentContext';

const application = { kind: 'application' as const, id: '7', label: 'ByteDance · Backend' };
const offer = { kind: 'offer' as const, id: '8', label: 'ByteDance · Offer' };
const resume = { kind: 'resume' as const, id: '9', label: 'Backend resume' };

function reduce(
  state: PilotAttachmentState,
  ...actions: Parameters<typeof pilotAttachmentStateReducer>[1][]
): PilotAttachmentState {
  return actions.reduce(pilotAttachmentStateReducer, state);
}

describe('PilotAttachmentContext attachment draft store', () => {
  it('restores attachments when switching back to an existing conversation', () => {
    const withConversationSeven = reduce(emptyPilotAttachmentState(),
      { type: 'set-active', key: 'conversation:7' },
      { type: 'add', attachment: application },
    );
    const onConversationEight = reduce(withConversationSeven, { type: 'set-active', key: 'conversation:8' });
    const backOnConversationSeven = reduce(onConversationEight, { type: 'set-active', key: 'conversation:7' });

    expect(onConversationEight.drafts['conversation:8']?.attachments ?? []).toEqual([]);
    expect(backOnConversationSeven.drafts['conversation:7']?.attachments).toEqual([application]);
  });

  it('isolates a fresh request draft from persisted conversations', () => {
    const state = reduce(emptyPilotAttachmentState(),
      { type: 'set-active', key: 'conversation:7' },
      { type: 'add', attachment: application },
      { type: 'set-active', key: 'new:15' },
      { type: 'add', attachment: offer },
    );

    expect(state.drafts['conversation:7']?.attachments).toEqual([application]);
    expect(state.drafts['new:15']?.attachments).toEqual([offer]);
  });

  it('removes and clears only the active draft', () => {
    const populated = reduce(emptyPilotAttachmentState(),
      { type: 'set-active', key: 'conversation:7' },
      { type: 'add', attachment: application },
      { type: 'add', attachment: resume },
      { type: 'set-active', key: 'conversation:8' },
      { type: 'add', attachment: offer },
    );
    const removed = reduce(populated,
      { type: 'set-active', key: 'conversation:7' },
      { type: 'remove', attachmentOrKey: 'application:7' },
    );
    const cleared = reduce(removed, { type: 'clear-active' });

    expect(removed.drafts['conversation:7']?.attachments).toEqual([resume]);
    expect(cleared.drafts['conversation:7']?.attachments).toEqual([]);
    expect(cleared.drafts['conversation:8']?.attachments).toEqual([offer]);
  });

  it('keeps the attachment-limit notice on the active draft and ignores adds without a key', () => {
    const attachments = Array.from({ length: 6 }, (_, index) => ({
      kind: 'resume' as const,
      id: String(index + 1),
      label: `Resume ${index + 1}`,
    }));
    const withoutKey = reduce(emptyPilotAttachmentState(), { type: 'add', attachment: attachments[0] });
    const limited = reduce(emptyPilotAttachmentState(),
      { type: 'set-active', key: 'new:15' },
      ...attachments.map((attachment) => ({ type: 'add' as const, attachment })),
    );

    expect(withoutKey).toEqual(emptyPilotAttachmentState());
    expect(limited.drafts['new:15']?.attachments).toHaveLength(5);
    expect(limited.drafts['new:15']?.message).toBeTruthy();
  });

  it('captures a normal new-draft key so only a successful send clears its attachments', () => {
    const normalNewDraft = reduce(emptyPilotAttachmentState(),
      { type: 'set-active', key: 'new:draft-1' },
      { type: 'add', attachment: application },
    );
    const sendKey = captureActiveAttachmentKey(normalNewDraft);
    const successfulSend = reduce(normalNewDraft, { type: 'clear-by-key', key: sendKey! });
    const failedSend = normalNewDraft;
    const abortedSend = normalNewDraft;

    expect(sendKey).toBe('new:draft-1');
    expect(successfulSend.drafts['new:draft-1']?.attachments).toEqual([]);
    expect(failedSend.drafts['new:draft-1']?.attachments).toEqual([application]);
    expect(abortedSend.drafts['new:draft-1']?.attachments).toEqual([application]);
  });
});
