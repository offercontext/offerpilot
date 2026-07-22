import { getOpportunityFitErrorMessage } from '@/components/opportunityFitCopy';
import type { OpportunityFitReview } from '@/types/opportunityFitReview';
import {
  classifyOpportunityFitFailure,
  normalizeOpportunityFitAssertions,
  type OpportunityFitDraftState,
  type OpportunityFitDraftStore,
} from './opportunityFitDraft';

export interface PilotTriagePayload {
  resume_id: number;
  jd_text: string;
  jd_source_label: string;
  candidate_assertions: string[];
  idempotency_key: string;
}

interface PilotTriageRunOptions {
  store: OpportunityFitDraftStore;
  applicationId: number;
  pilotDraftKey: string;
  draft: OpportunityFitDraftState;
  existingKey: string | null;
  createReview: (applicationId: number, payload: PilotTriagePayload) => Promise<OpportunityFitReview>;
  isContextCurrent?: () => boolean;
}

const requestGenerations = new WeakMap<OpportunityFitDraftStore, number>();
const deepReviewRequestGenerations = new WeakMap<OpportunityFitDraftStore, number>();

interface PilotDeepReviewRunOptions {
  store: OpportunityFitDraftStore;
  applicationId: number;
  pilotDraftKey: string;
  draft: OpportunityFitDraftState;
  review: OpportunityFitReview;
  createReview: (applicationId: number, reviewId: number) => Promise<OpportunityFitReview>;
  isContextCurrent?: () => boolean;
}

function isRunCurrent(
  options: PilotTriageRunOptions,
  attemptKey: string,
  generation: number,
  input: Pick<OpportunityFitDraftState, 'applicationId' | 'pilotDraftKey' | 'resumeID' | 'jdText' | 'assertionsText'>,
): boolean {
  const current = options.store.getState();
  return requestGenerations.get(options.store) === generation
    && options.isContextCurrent?.() !== false
    && current.applicationId === input.applicationId
    && current.pilotDraftKey === input.pilotDraftKey
    && current.resumeID === input.resumeID
    && current.jdText === input.jdText
    && current.assertionsText === input.assertionsText
    && current.triageAttemptKey === attemptKey;
}

export async function runPilotTriage(options: PilotTriageRunOptions): Promise<void> {
  const candidateAssertions = normalizeOpportunityFitAssertions(options.draft.assertionsText);
  const normalizedInput = {
    applicationId: options.applicationId,
    pilotDraftKey: options.pilotDraftKey,
    resumeID: options.draft.resumeID,
    jdText: options.draft.jdText.trim(),
    assertionsText: candidateAssertions.join('\n'),
  };
  const triageAttemptKey = options.existingKey ?? options.draft.triageAttemptKey ?? crypto.randomUUID();
  const generation = (requestGenerations.get(options.store) ?? 0) + 1;
  requestGenerations.set(options.store, generation);

  options.store.dispatch({ type: 'set_attempt_key', key: triageAttemptKey });
  options.store.dispatch({ type: 'set_jd', jdText: normalizedInput.jdText });
  options.store.dispatch({ type: 'set_assertions', assertionsText: normalizedInput.assertionsText });
  options.store.dispatch({ type: 'set_attempt_key', key: triageAttemptKey });
  options.store.dispatch({ type: 'set_phase', phase: 'triage_loading' });

  const payload: PilotTriagePayload = {
    resume_id: normalizedInput.resumeID!,
    jd_text: normalizedInput.jdText,
    jd_source_label: '用户粘贴 JD',
    candidate_assertions: candidateAssertions,
    idempotency_key: triageAttemptKey,
  };

  try {
    const result = await options.createReview(options.applicationId, payload);
    if (!isRunCurrent(options, triageAttemptKey, generation, normalizedInput)) return;
    options.store.dispatch({ type: 'set_review', review: result });
  } catch (error) {
    if (!isRunCurrent(options, triageAttemptKey, generation, normalizedInput)) return;
    const disposition = classifyOpportunityFitFailure(error);
    options.store.dispatch({
      type: 'set_error',
      error: getOpportunityFitErrorMessage(error),
      disposition,
    });
    options.store.dispatch({ type: 'set_phase', phase: 'confirm_triage' });
  }
}

function isDeepReviewRunCurrent(
  options: PilotDeepReviewRunOptions,
  generation: number,
): boolean {
  const current = options.store.getState();
  return deepReviewRequestGenerations.get(options.store) === generation
    && options.isContextCurrent?.() !== false
    && current.applicationId === options.applicationId
    && current.pilotDraftKey === options.pilotDraftKey
    && current.resumeID === options.draft.resumeID
    && current.jdText === options.draft.jdText
    && current.assertionsText === options.draft.assertionsText
    && current.review?.id === options.review.id
    && current.phase === 'deep_review_loading';
}

export async function runPilotDeepReview(options: PilotDeepReviewRunOptions): Promise<void> {
  const generation = (deepReviewRequestGenerations.get(options.store) ?? 0) + 1;
  deepReviewRequestGenerations.set(options.store, generation);

  options.store.dispatch({ type: 'set_error', error: null, disposition: null });
  options.store.dispatch({ type: 'set_phase', phase: 'deep_review_loading' });

  try {
    const result = await options.createReview(options.applicationId, options.review.id);
    if (!isDeepReviewRunCurrent(options, generation)) return;
    options.store.dispatch({ type: 'set_review', review: result });
  } catch (error) {
    if (!isDeepReviewRunCurrent(options, generation)) return;
    const disposition = classifyOpportunityFitFailure(error);
    options.store.dispatch({
      type: 'set_error',
      error: getOpportunityFitErrorMessage(error),
      disposition,
    });
    options.store.dispatch({ type: 'set_phase', phase: 'triage_ready' });
  }
}
