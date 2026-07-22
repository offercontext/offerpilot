import { describe, expect, it } from 'vitest';

import type { OpportunityFitReview } from '@/types/opportunityFitReview';
import {
  createInitialOpportunityFitDraft,
  opportunityFitDraftReducer,
} from './opportunityFitDraft';

const review: OpportunityFitReview = {
  id: 11,
  application_id: 7,
  resume_id: 3,
  status: 'triage_complete',
  summary: {
    text: 'Candidate has a plausible fit.',
    evidence_refs: [],
  },
  recommendation: 'advance',
  source_fingerprint_sha256: 'source-hash',
  triage_sha256: 'triage-hash',
  deep_review_sha256: null,
  created_at: '2026-07-22T00:00:00Z',
  deep_reviewed_at: null,
  source: {
    application: { id: 7, company_name: 'Example', position_name: 'Engineer' },
    resume: { id: 3, title: 'Resume', sha256: 'resume-hash' },
    jd: { source_label: 'Pasted JD', sha256: 'jd-hash', text: 'Build things.' },
    candidate_assertions: [],
  },
  triage: {
    summary: { text: 'Candidate has a plausible fit.', evidence_refs: [] },
    recommendation: 'advance',
    hard_constraints: [],
    fit_signals: [],
    gaps: [],
    deadline: { status: 'not_stated', text: '', evidence_refs: [] },
    next_questions: [],
  },
  deep_review: null,
};

describe('opportunityFitDraftReducer', () => {
  it('creates a complete reusable draft state', () => {
    expect(createInitialOpportunityFitDraft(7, 'draft-1')).toEqual({
      applicationId: 7,
      pilotDraftKey: 'draft-1',
      phase: 'collect_input',
      resumeID: undefined,
      jdText: '',
      assertionsText: '',
      review: null,
      actionError: null,
      triageAttemptKey: null,
    });
  });

  it('returns the original object for an unknown action', () => {
    const state = createInitialOpportunityFitDraft(7, 'draft-1');

    const next = opportunityFitDraftReducer(state, { type: 'unknown' } as never);

    expect(next).toBe(state);
  });

  it('returns the original object for an invalid phase', () => {
    const state = createInitialOpportunityFitDraft(7, 'draft-1');

    const next = opportunityFitDraftReducer(state, {
      type: 'set_phase',
      phase: 'not-a-phase',
    } as never);

    expect(next).toBe(state);
  });

  it('invalidates the attempt key when input changes', () => {
    const withKey = opportunityFitDraftReducer(
      createInitialOpportunityFitDraft(7, 'draft-1'),
      { type: 'set_attempt_key', key: 'attempt-1' },
    );

    const withResume = opportunityFitDraftReducer(withKey, { type: 'set_resume', resumeID: 3 });
    const withJd = opportunityFitDraftReducer(withKey, { type: 'set_jd', jdText: 'Build things.' });
    const withAssertions = opportunityFitDraftReducer(withKey, {
      type: 'set_assertions',
      assertionsText: 'I have shipped production systems.',
    });

    expect(withResume.triageAttemptKey).toBeNull();
    expect(withJd.triageAttemptKey).toBeNull();
    expect(withAssertions.triageAttemptKey).toBeNull();
  });

  it('stores a review as an available triage result and clears its successful attempt key', () => {
    const withKey = opportunityFitDraftReducer(
      createInitialOpportunityFitDraft(7, 'draft-1'),
      { type: 'set_attempt_key', key: 'attempt-1' },
    );

    const next = opportunityFitDraftReducer(withKey, { type: 'set_review', review });

    expect(next.review).toBe(review);
    expect(next.phase).toBe('triage_ready');
    expect(next.triageAttemptKey).toBeNull();
  });

  it('retains the attempt key across an unknown result and a remount-style retry', () => {
    const initial = createInitialOpportunityFitDraft(7, 'draft-1');
    const loading = opportunityFitDraftReducer(initial, {
      type: 'set_attempt_key',
      key: 'attempt-1',
    });
    const timedOut = opportunityFitDraftReducer(loading, {
      type: 'set_error',
      error: '结果未知',
    });
    const reset = opportunityFitDraftReducer(timedOut, {
      type: 'set_phase',
      phase: 'confirm_triage',
    });

    const remounted = reset;
    const retried = opportunityFitDraftReducer(remounted, {
      type: 'set_phase',
      phase: 'triage_loading',
    });

    expect(retried.triageAttemptKey).toBe('attempt-1');
    expect(retried.actionError).toBe('结果未知');
  });

  it('clears the attempt key only when explicitly requested', () => {
    const withKey = opportunityFitDraftReducer(
      createInitialOpportunityFitDraft(7, 'draft-1'),
      { type: 'set_attempt_key', key: 'attempt-1' },
    );

    const next = opportunityFitDraftReducer(withKey, { type: 'set_attempt_key', key: null });

    expect(next.triageAttemptKey).toBeNull();
  });

  it('does not create a partial state from an illegal current state', () => {
    const illegalState = { phase: 'collect_input' } as never;

    const next = opportunityFitDraftReducer(illegalState, { type: 'set_jd', jdText: 'JD' });

    expect(next).toBe(illegalState);
  });
});
