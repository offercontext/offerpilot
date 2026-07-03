import { describe, expect, it } from 'vitest';
import { derivePipelineInsights } from './pipelineInsights';
import type { Application } from '@/types/application';
import type { Offer } from '@/types/offer';
import type { PracticeStats } from '@/types/question';

const now = '2026-07-03T09:00:00+08:00';

function makeApplication(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    company_name: 'Acme',
    position_name: 'Frontend Engineer',
    job_url: '',
    status: 'applied',
    source: '',
    notes: '',
    applied_at: '2026-06-01',
    created_at: '2026-06-01T09:00:00+08:00',
    updated_at: '2026-06-18',
    ...overrides,
  };
}

function makeOffer(overrides: Partial<Offer> = {}): Offer {
  return {
    id: 1,
    application_id: 1,
    company_name: 'Acme',
    position_name: 'Frontend Engineer',
    status: 'pending',
    base_monthly: 0,
    months_per_year: 12,
    signing_bonus: 0,
    equity: '',
    perks: '',
    deadline: '2026-07-04',
    notes: '',
    assessment: '',
    total_cash: 0,
    created_at: '2026-07-01T09:00:00+08:00',
    updated_at: '2026-07-01T09:00:00+08:00',
    ...overrides,
  };
}

function makePracticeStats(overrides: Partial<PracticeStats> = {}): PracticeStats {
  return {
    total: 20,
    new: 3,
    practicing: 12,
    mastered: 5,
    due: 0,
    today_reviews: 0,
    streak_days: 0,
    ...overrides,
  };
}

describe('derivePipelineInsights', () => {
  it('promotes an offer deadline within 48 hours to P0 with deadline evidence and offer action', () => {
    const insights = derivePipelineInsights({
      apps: [],
      events: [],
      offers: [makeOffer()],
      now,
    });

    expect(insights).toContainEqual(
      expect.objectContaining({
        kind: 'offer_deadline',
        priority: 'p0',
        evidence: expect.arrayContaining(['Deadline: 2026-07-04']),
        primaryAction: expect.objectContaining({
          label: 'Open offer center',
          target: 'offers',
        }),
      }),
    );
  });

  it('marks an application stale after 15 days without updates and targets the board', () => {
    const insights = derivePipelineInsights({
      apps: [makeApplication()],
      events: [],
      offers: [],
      now,
    });

    expect(insights).toContainEqual(
      expect.objectContaining({
        kind: 'stale_application',
        priority: 'p1',
        reason: expect.stringContaining('15 days without updates'),
        primaryAction: expect.objectContaining({
          target: 'board',
        }),
      }),
    );
  });

  it('creates a P1 question_due insight when 12 questions are due', () => {
    const insights = derivePipelineInsights({
      apps: [],
      events: [],
      offers: [],
      practiceStats: makePracticeStats({ due: 12 }),
      now,
    });

    expect(insights).toContainEqual(
      expect.objectContaining({
        kind: 'question_due',
        priority: 'p1',
        questionCount: 12,
        primaryAction: expect.objectContaining({
          target: 'questions',
        }),
      }),
    );
  });
});
