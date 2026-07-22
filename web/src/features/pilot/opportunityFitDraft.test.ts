// @vitest-environment jsdom
import { act, createElement, useSyncExternalStore } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import type { OpportunityFitReview } from '@/types/opportunityFitReview';
import {
  classifyOpportunityFitFailure,
  createInitialOpportunityFitDraft,
  createOpportunityFitDraftStore,
  opportunityFitDraftReducer,
  type OpportunityFitDraftStore,
} from './opportunityFitDraft';

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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
      disposition: 'unknown',
    });

    expect(timedOut.triageAttemptKey).toBe('attempt-1');
    expect(timedOut.actionError).toBe('结果未知');
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

  it('clears the attempt key for a definite no-write failure', () => {
    const withKey = opportunityFitDraftReducer(
      createInitialOpportunityFitDraft(7, 'draft-1'),
      { type: 'set_attempt_key', key: 'attempt-1' },
    );

    const next = opportunityFitDraftReducer(withKey, {
      type: 'set_error',
      error: '输入无效',
      disposition: 'definite_no_write',
    });

    expect(next.triageAttemptKey).toBeNull();
  });

  it.each([
    [{ response: { status: 422 } }, '422'],
    [{ response: { status: 404 } }, '404'],
    [{ response: { status: 502, data: { error_code: 'opportunity_fit_provider_error' } } }, 'provider 502'],
    [{ response: { status: 502, data: { error_code: 'opportunity_fit_unverifiable' } } }, 'unverifiable 502'],
  ] as const)('classifies %s as definite_no_write', (failure, _label) => {
    expect(classifyOpportunityFitFailure(failure)).toBe('definite_no_write');
  });

  it.each([
    [{ response: { status: 500 } }, '500'],
    [{ response: { status: 502, data: {} } }, 'unclassified 502'],
    [{ response: { status: 502, data: { error_code: 'other' } } }, 'other 502'],
    [{ response: { status: 504 } }, 'gateway 504'],
    [{ response: { status: 200, data: null } }, 'invalid response body'],
    [new Error('timeout'), 'timeout'],
    [new TypeError('offline'), 'offline'],
    [undefined, 'lost response'],
  ] as const)('classifies %s as unknown', (failure, _label) => {
    expect(classifyOpportunityFitFailure(failure)).toBe('unknown');
  });

  it('rejects malformed reviews without changing the draft phase', () => {
    const state = createInitialOpportunityFitDraft(7, 'draft-1');

    const next = opportunityFitDraftReducer(state, {
      type: 'set_review',
      review: {},
    } as never);

    expect(next).toBe(state);
    expect(next.review).toBeNull();
    expect(next.phase).toBe('collect_input');
  });
});

function DraftStoreView({ store }: { store: OpportunityFitDraftStore }) {
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);

  return createElement(
    'output',
    { 'data-testid': 'draft-state' },
    state.triageAttemptKey ?? 'no-key',
  );
}

describe('opportunity fit draft external store', () => {
  let container: HTMLDivElement | undefined;
  let root: Root | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    container?.remove();
    root = undefined;
    container = undefined;
  });

  function mount(store: OpportunityFitDraftStore) {
    const mountedContainer = document.createElement('div');
    container = mountedContainer;
    document.body.appendChild(mountedContainer);
    root = createRoot(mountedContainer);
    act(() => root?.render(createElement(DraftStoreView, { store })));
    return mountedContainer;
  }

  it('retains the same unknown-result key across a real unmount and remount', () => {
    const store = createOpportunityFitDraftStore(7, 'draft-1');
    const firstMount = mount(store);

    act(() => {
      store.dispatch({ type: 'set_attempt_key', key: 'attempt-1' });
      store.dispatch({
        type: 'set_error',
        error: '结果未知',
        disposition: 'unknown',
      });
    });
    expect(firstMount.querySelector('[data-testid="draft-state"]')?.textContent).toBe('attempt-1');

    act(() => root?.unmount());
    container?.remove();
    root = undefined;
    container = undefined;

    const secondMount = mount(store);
    expect(secondMount.querySelector('[data-testid="draft-state"]')?.textContent).toBe('attempt-1');

    act(() => store.dispatch({ type: 'set_phase', phase: 'triage_loading' }));
    expect(store.getState().triageAttemptKey).toBe('attempt-1');
    expect(secondMount.querySelector('[data-testid="draft-state"]')?.textContent).toBe('attempt-1');
  });
});
