import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '@/types/chat';
import { buildTurns, collectEvidence } from './model';

function msg(patch: Partial<ChatMessage> & Pick<ChatMessage, 'role'>): ChatMessage {
  return {
    id: patch.id ?? 1,
    conversation_id: patch.conversation_id ?? 1,
    role: patch.role,
    content: patch.content ?? '',
    tool_calls: patch.tool_calls,
    tool_call_id: patch.tool_call_id,
    created_at: patch.created_at ?? '2026-07-06T12:00:00+08:00',
  };
}

describe('buildTurns evidence normalization', () => {
  it('attaches application evidence from tool results to the assistant turn', () => {
    const turns = buildTurns([
      msg({ role: 'user', content: 'show apps' }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([
          {
            id: 7,
            company_name: 'ByteDance',
            position_name: 'Backend Engineer',
            status: 'interview',
            source: 'manual',
            applied_at: '2026-07-01',
          },
        ]),
      }),
      msg({ role: 'assistant', content: 'You have one active interview.' }),
    ]);

    expect(turns[1].steps?.[0]).toMatchObject({
      name: 'list_applications',
      detail: 'ByteDance',
      evidence: [
        {
          id: 'application-7',
          kind: 'application',
          title: 'ByteDance',
          meta: 'Backend Engineer \u00b7 interview \u00b7 2026-07-01',
          source: 'list_applications',
        },
      ],
    });
  });

  it('keeps malformed tool results as an unavailable detail instead of throwing', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'search_knowledge', args: { query: 'system design' } }]),
      }),
      msg({ role: 'tool', content: '{bad json' }),
      msg({ role: 'assistant', content: 'I searched.' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'search_knowledge',
      detail: 'system design',
      evidenceUnavailable: true,
    });
  });

  it('aggregates newest evidence first across visible turns', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_offers', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 3, company_name: 'OpenAI', position_name: 'PM', total_cash: 600000 }]),
      }),
      msg({ role: 'assistant', content: 'Offer found.' }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 4, company_name: 'Anthropic', position_name: 'PM', status: 'applied' }]),
      }),
      msg({ role: 'assistant', content: 'Application found.' }),
    ]);

    expect(collectEvidence(turns).map((item) => item.title)).toEqual(['Anthropic', 'OpenAI']);
  });
});
