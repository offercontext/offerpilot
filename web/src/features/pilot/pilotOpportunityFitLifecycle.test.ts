import { describe, expect, it } from 'vitest';
import { createOpportunityFitDraftStore } from './opportunityFitDraft';
import { runPilotDeepReview, runPilotTriage } from './pilotOpportunityFitLifecycle';
import type { OpportunityFitReview } from '@/types/opportunityFitReview';

const review = {
  id: 1,
  application_id: 7,
  resume_id: 3,
  status: 'triage_complete',
  recommendation: 'advance',
  summary: { text: 'Summary', evidence_refs: [{ source: 'jd', path: '/text', excerpt: 'JD' }] },
  source_fingerprint_sha256: 'source',
  triage_sha256: 'triage',
  deep_review_sha256: null,
  created_at: '2026-07-22T00:00:00Z',
  deep_reviewed_at: null,
  source: {
    application: { id: 7, company_name: 'Example', position_name: 'Engineer' },
    resume: { id: 3, title: 'Resume', sha256: 'resume' },
    jd: { source_label: 'Pasted JD', sha256: 'jd', text: 'JD' },
    candidate_assertions: [],
  },
  triage: {
    summary: { text: 'Summary', evidence_refs: [{ source: 'jd', path: '/text', excerpt: 'JD' }] },
    recommendation: 'advance',
    hard_constraints: [],
    fit_signals: [],
    gaps: [],
    deadline: { status: 'not_stated', text: '', evidence_refs: [] },
    next_questions: [],
  },
  deep_review: null,
} satisfies OpportunityFitReview;

const deepReview = {
  ...review,
  status: 'deep_reviewed',
  deep_review_sha256: 'deep',
  deep_reviewed_at: '2026-07-22T00:01:00Z',
  deep_review: {
    strengths: [],
    gaps_to_address: [],
    questions_to_clarify: [],
    recommended_path: 'prepare_materials',
    next_actions: [],
  },
} satisfies OpportunityFitReview;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe('Pilot triage lifecycle', () => {
  it('discards a response after the draft input changes while the request is pending', async () => {
    const store = createOpportunityFitDraftStore(7, 'draft-1');
    store.dispatch({ type: 'set_resume', resumeID: 3 });
    store.dispatch({ type: 'set_jd', jdText: 'JD' });
    const request = deferred<OpportunityFitReview>();
    const run = runPilotTriage({
      store,
      applicationId: 7,
      pilotDraftKey: 'draft-1',
      draft: store.getState(),
      existingKey: null,
      createReview: () => request.promise,
    });

    store.dispatch({ type: 'set_jd', jdText: 'Changed JD' });
    request.resolve(review);
    await run;

    expect(store.getState().review).toBeNull();
    expect(store.getState().triageAttemptKey).toBeNull();
  });

  it('preserves the same key and payload when an unknown failure is retried', async () => {
    const store = createOpportunityFitDraftStore(7, 'draft-1');
    store.dispatch({ type: 'set_resume', resumeID: 3 });
    store.dispatch({ type: 'set_jd', jdText: ' JD ' });
    let calls = 0;
    await runPilotTriage({
      store,
      applicationId: 7,
      pilotDraftKey: 'draft-1',
      draft: store.getState(),
      existingKey: 'attempt-1',
      createReview: async (_applicationId, payload) => {
        calls += 1;
        expect(payload).toMatchObject({ jd_text: 'JD', idempotency_key: 'attempt-1' });
        throw { response: { status: 500 } };
      },
    });

    expect(calls).toBe(1);
    expect(store.getState().triageAttemptKey).toBe('attempt-1');
    expect(store.getState().triageFailureDisposition).toBe('unknown');
  });

  it('accepts only the newest request when two requests share an idempotency key', async () => {
    const store = createOpportunityFitDraftStore(7, 'draft-1');
    store.dispatch({ type: 'set_resume', resumeID: 3 });
    store.dispatch({ type: 'set_jd', jdText: 'JD' });
    const first = deferred<OpportunityFitReview>();
    const second = deferred<OpportunityFitReview>();
    let calls = 0;
    const createReview = () => {
      calls += 1;
      return calls === 1 ? first.promise : second.promise;
    };
    const firstRun = runPilotTriage({
      store,
      applicationId: 7,
      pilotDraftKey: 'draft-1',
      draft: store.getState(),
      existingKey: 'attempt-1',
      createReview,
    });
    const secondRun = runPilotTriage({
      store,
      applicationId: 7,
      pilotDraftKey: 'draft-1',
      draft: store.getState(),
      existingKey: 'attempt-1',
      createReview,
    });

    first.resolve(review);
    await firstRun;
    expect(store.getState().review).toBeNull();
    second.resolve(review);
    await secondRun;
    expect(store.getState().review?.id).toBe(review.id);
  });
});

describe('Pilot deep review lifecycle', () => {
  it('discards a deep-review response after the Pilot context is canceled', async () => {
    const store = createOpportunityFitDraftStore(7, 'draft-1');
    store.dispatch({ type: 'set_review', review });
    const request = deferred<OpportunityFitReview>();
    let contextCurrent = true;
    const run = runPilotDeepReview({
      store,
      applicationId: 7,
      pilotDraftKey: 'draft-1',
      draft: store.getState(),
      review,
      createReview: () => request.promise,
      isContextCurrent: () => contextCurrent,
    });

    contextCurrent = false;
    request.resolve(deepReview);
    await run;

    expect(store.getState().review).toBe(review);
    expect(store.getState().phase).toBe('deep_review_loading');
  });

  it('accepts only the newest deep-review response for the same review', async () => {
    const store = createOpportunityFitDraftStore(7, 'draft-1');
    store.dispatch({ type: 'set_review', review });
    const first = deferred<OpportunityFitReview>();
    const second = deferred<OpportunityFitReview>();
    let calls = 0;
    const createReview = () => {
      calls += 1;
      return calls === 1 ? first.promise : second.promise;
    };
    const firstRun = runPilotDeepReview({
      store,
      applicationId: 7,
      pilotDraftKey: 'draft-1',
      draft: store.getState(),
      review,
      createReview,
    });
    const secondRun = runPilotDeepReview({
      store,
      applicationId: 7,
      pilotDraftKey: 'draft-1',
      draft: store.getState(),
      review,
      createReview,
    });

    first.resolve(deepReview);
    await firstRun;
    expect(store.getState().phase).toBe('deep_review_loading');
    second.resolve(deepReview);
    await secondRun;
    expect(calls).toBe(2);
    expect(store.getState().review?.deep_review).toEqual(deepReview.deep_review);
    expect(store.getState().phase).toBe('deep_review_ready');
  });
});
