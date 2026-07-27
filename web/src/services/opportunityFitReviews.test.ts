import { afterEach, describe, expect, it, vi } from 'vitest';
import { listOpportunityFitReviews, listOpportunityFitV2Reviews } from './opportunityFitReviews';

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));

vi.mock('./http', () => ({
  createApiClient: () => ({ get: getMock, post: vi.fn() }),
}));

afterEach(() => getMock.mockReset());

describe('opportunity fit history schema routing', () => {
  it('keeps v1 history out of the v2 list and v2 history out of the v1 list', async () => {
    getMock.mockResolvedValue({
      data: [
        { id: 1, application_id: 9, status: 'triage_complete' },
        { id: 2, review_id: 2, application_id: 9, schema_version: 2, stage_count: 1 },
      ],
    });

    await expect(listOpportunityFitReviews(9)).resolves.toEqual([
      { id: 1, application_id: 9, status: 'triage_complete' },
    ]);
    await expect(listOpportunityFitV2Reviews(9)).resolves.toEqual([
      { id: 2, review_id: 2, application_id: 9, schema_version: 2, stage_count: 1 },
    ]);
  });
});
