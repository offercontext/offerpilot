import { afterEach, describe, expect, it, vi } from 'vitest';
import { confirmAction, createSseParser, sendChat, streamChat, streamConfirmAction } from './chat';
import source from './chat.ts?raw';
import type { ChatStreamEvent, PilotPageContext } from '@/types/chat';

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }));

vi.mock('./http', () => ({
  createApiClient: () => ({ post: postMock }),
}));

const originalFetch = globalThis.fetch;

function sseResponse(frames: string) {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frames));
        controller.close();
      },
    }),
    { status: 200, headers: { 'content-type': 'text/event-stream' } },
  );
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  postMock.mockReset();
  vi.restoreAllMocks();
});

describe('settings service v0.1 contract', () => {
  it('exposes provider testing, fallback provider, and safe backup endpoints', () => {
    expect(source).toContain('fallback_provider_id');
    expect(source).toContain('/settings/providers/test');
    expect(source).toContain('/settings/backup');
    expect(source).toContain('testProviderConnection');
    expect(source).toContain('getSettingsBackup');
    expect(source).not.toContain('api_key: string;');
  });

  it('allows chat requests and confirmations to be interrupted', () => {
    expect(source).toContain('options?: ChatRequestOptions');
    expect(source).toContain('signal?: AbortSignal');
    expect(source).toContain('{ signal: options?.signal }');
  });

  it('exposes the undo endpoint for the latest AI write', () => {
    expect(source).toContain('undoLastWrite');
    expect(source).toContain('/chat/undo-last-write');
  });

  it('exposes conversation management updates for rename, pin, archive, and context clearing', () => {
    expect(source).toContain('UpdateConversationPayload');
    expect(source).toContain('updateConversation');
    expect(source).toContain('patch<Conversation>');
    expect(source).toContain('`/chat/conversations/${id}`');
  });

  it('parses SSE events across chunk boundaries', () => {
    const events: ChatStreamEvent[] = [];
    const parser = createSseParser((event) => events.push(event));
    parser.push('event: meta\nid: run:1\ndata: {"event":"meta","seq":1,"data":{"stream_version":"pilot-sse-v1"}}\n');
    expect(events).toHaveLength(0);

    parser.push('\nevent: completed\nid: run:2\ndata: {"event":"completed","seq":2,"data":{"response":{"type":"message","conversation_id":7,"message":"done"}}}\n\n');

    expect(events).toHaveLength(2);
    expect(events[0].event).toBe('meta');
    expect(events[0].data.stream_version).toBe('pilot-sse-v1');
    expect(events[1].event).toBe('completed');
    expect(events[1].data.response).toEqual({ type: 'message', conversation_id: 7, message: 'done' });
  });

  it('streams chat through the pilot SSE endpoint', async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse(
        'event: completed\nid: run:1\ndata: {"event":"completed","seq":1,"data":{"response":{"type":"message","conversation_id":3,"message":"ok"}}}\n\n',
      ),
    );
    globalThis.fetch = fetchMock as typeof fetch;
    const events: ChatStreamEvent[] = [];

    const response = await streamChat('hi', 0, { context_type: 'workspace', mode: 'general' }, { onEvent: (event) => events.push(event) });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/chat/stream',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ message: 'hi', conversation_id: 0, context_type: 'workspace', mode: 'general' }),
      }),
    );
    expect(events.map((event) => event.event)).toEqual(['completed']);
    expect(response).toEqual({ type: 'message', conversation_id: 3, message: 'ok' });
  });

  it('sends page context unchanged through JSON and omits it when absent', async () => {
    const pageContext: PilotPageContext = {
      view: 'board',
      label: '投递看板',
      entity: { kind: 'application', id: '12', label: '启明智能 · 算法工程师' },
      filters: [{ key: 'status', label: '状态', value: '面试' }],
    };
    postMock
      .mockResolvedValueOnce({ data: { type: 'message', conversation_id: 3, message: 'ok' } })
      .mockResolvedValueOnce({ data: { type: 'message', conversation_id: 3, message: 'ok' } });

    await sendChat('hi', 3, { context_type: 'workspace', page_context: pageContext });
    await sendChat('again', 3, { context_type: 'workspace' });

    expect(postMock.mock.calls[0][1]).toEqual({
      message: 'hi',
      conversation_id: 3,
      context_type: 'workspace',
      page_context: pageContext,
    });
    expect(postMock.mock.calls[0][1].page_context).toBe(pageContext);
    expect(postMock.mock.calls[1][1]).not.toHaveProperty('page_context');
  });

  it('sends page context unchanged through SSE and omits it when absent', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      sseResponse(
        'event: completed\nid: run:1\ndata: {"event":"completed","seq":1,"data":{"response":{"type":"message","conversation_id":3,"message":"ok"}}}\n\n',
      ),
    );
    globalThis.fetch = fetchMock as typeof fetch;
    const pageContext: PilotPageContext = {
      view: 'calendar',
      label: '日历',
      filters: [{ key: 'month', label: '月份', value: '2026-07' }],
    };

    await streamChat('hi', 3, { page_context: pageContext });
    await streamChat('again', 3);

    const firstBody = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    const secondBody = JSON.parse(fetchMock.mock.calls[1][1]?.body as string);
    expect(firstBody.page_context).toEqual(pageContext);
    expect(secondBody).not.toHaveProperty('page_context');
  });

  it('streams confirmation through the pilot SSE endpoint', async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse(
        'event: completed\nid: run:1\ndata: {"event":"completed","seq":1,"data":{"response":{"type":"message","conversation_id":3,"message":"confirmed"}}}\n\n',
      ),
    );
    globalThis.fetch = fetchMock as typeof fetch;

    const response = await streamConfirmAction(3, {
      approved: true,
      edited_args: { status: 'offer' },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/chat/confirm/stream',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ conversation_id: 3, approved: true, edited_args: { status: 'offer' } }),
      }),
    );
    expect(response).toEqual({ type: 'message', conversation_id: 3, message: 'confirmed' });
  });

  it('serializes identical confirmation input for JSON and SSE endpoints', async () => {
    const input = { approved: false, rejection_feedback: 'Keep the current status.' };
    postMock.mockResolvedValueOnce({
      data: { type: 'message', conversation_id: 3, message: 'kept' },
    });
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      sseResponse(
        'event: completed\nid: run:1\ndata: {"event":"completed","seq":1,"data":{"response":{"type":"message","conversation_id":3,"message":"kept"}}}\n\n',
      ),
    );
    globalThis.fetch = fetchMock as typeof fetch;

    await confirmAction(3, input);
    await streamConfirmAction(3, input);

    expect(postMock).toHaveBeenCalledWith(
      '/chat/confirm',
      { conversation_id: 3, ...input },
      { signal: undefined },
    );
    const streamBody = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(streamBody).toEqual({ conversation_id: 3, ...input });
  });

  it('uses Chinese fallback messages for broken SSE streams', async () => {
    globalThis.fetch = vi.fn(async () => new Response(null, { status: 200 })) as typeof fetch;

    await expect(streamChat('hi')).rejects.toThrow('对话连接中断，请稍后重试。');

    globalThis.fetch = vi.fn(async () => sseResponse('event: status\ndata: {"event":"status","seq":1,"data":{}}\n\n')) as typeof fetch;

    await expect(streamChat('hi')).rejects.toThrow('对话没有返回完整结果，请重试。');
  });
});
