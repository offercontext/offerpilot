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
