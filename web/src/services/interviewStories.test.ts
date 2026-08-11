import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiGet, apiPost, createApiClient } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  createApiClient: vi.fn(),
}));

vi.mock('./http', () => ({ createApiClient }));
createApiClient.mockReturnValue({ get: apiGet, post: apiPost });

const service = await import('./interviewStories');

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});

describe('interview story service', () => {
  it('uses the UI and Pilot proposal endpoints without chat APIs', async () => {
    const input = {
      target_story_id: null,
      expected_current_version_id: null,
      expected_story_revision: null,
      selections: [],
      assertions: [],
      idempotency_key: 'story-service-key-0001',
    };
    apiPost.mockResolvedValue({ data: { id: 7, attempt_status: 'generating', generation_revision: 1, source_fingerprint: 'fp', retry_after_ms: 1000 } });

    await service.createInterviewStoryProposal(input);
    await service.createInterviewStoryProposal(input, 'pilot');

    expect(apiPost).toHaveBeenNthCalledWith(1, '/interview-story-proposals', input);
    expect(apiPost).toHaveBeenNthCalledWith(2, '/pilot/interview-story-proposals', input);
  });

  it('uses only Story APIs for archive and version history reads', async () => {
    apiGet.mockResolvedValue({ data: [] });
    apiPost.mockResolvedValue({ data: { id: 5, status: 'archived' } });

    await service.listInterviewStoryVersions(5);
    await service.archiveInterviewStory(5, 2);

    expect(apiGet).toHaveBeenCalledWith('/interview-stories/5/versions');
    expect(apiPost).toHaveBeenCalledWith('/interview-stories/5/archive', { expected_story_revision: 2 });
  });

  it('reads explicit Story source candidates without any write request', async () => {
    apiGet.mockResolvedValue({ data: { resumes: [], interview_notes: [], mock_turns: [] } });

    await service.listInterviewStorySourceCandidates();
    await service.listInterviewStorySourceCandidates(9);

    expect(apiGet).toHaveBeenNthCalledWith(1, '/interview-story-sources', { params: undefined });
    expect(apiGet).toHaveBeenNthCalledWith(2, '/interview-story-sources', { params: { review_note_id: 9 } });
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('sends the user-owned manual idempotency key only to Story save APIs', async () => {
    const input = {
      content: { title: '一次延迟排查', blocks: [], capability_labels: [], applicable_questions: [], fact_gap_codes: ['missing_result'] },
      evidence_links: [], selections: [], assertions: [], expected_current_version_id: null,
      idempotency_key: 'manual-story-service-key-01',
    };
    apiPost.mockResolvedValue({ data: { id: 5 } });

    await service.createInterviewStory(input);

    expect(apiPost).toHaveBeenCalledWith('/interview-stories', input);
  });

  it('keeps the safe provider-unknown Attempt identity from a 502 response', async () => {
    const input = {
      target_story_id: null,
      expected_current_version_id: null,
      expected_story_revision: null,
      selections: [],
      assertions: [],
      idempotency_key: 'story-provider-unknown-key',
    };
    apiPost.mockRejectedValue({
      response: {
        status: 502,
        data: { error_code: 'story_provider_error', id: 44, attempt_status: 'provider_unknown' },
      },
    });

    await expect(service.createInterviewStoryProposal(input)).rejects.toMatchObject({
      status: 502,
      code: 'story_provider_error',
      attemptId: 44,
    });
  });
});
