import { afterEach, describe, expect, it, vi } from 'vitest';
import { createSseParser, streamChat, streamConfirmAction } from './chat';
import source from './chat.ts?raw';
import type { ChatStreamEvent } from '@/types/chat';

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

  it('streams confirmation through the pilot SSE endpoint', async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse(
        'event: completed\nid: run:1\ndata: {"event":"completed","seq":1,"data":{"response":{"type":"message","conversation_id":3,"message":"confirmed"}}}\n\n',
      ),
    );
    globalThis.fetch = fetchMock as typeof fetch;

    const response = await streamConfirmAction(3, true);

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/chat/confirm/stream',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ conversation_id: 3, approved: true }),
      }),
    );
    expect(response).toEqual({ type: 'message', conversation_id: 3, message: 'confirmed' });
  });
});
