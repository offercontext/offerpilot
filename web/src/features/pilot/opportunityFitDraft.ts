import type { OpportunityFitReview } from '@/types/opportunityFitReview';

export type OpportunityFitDraftPhase =
  | 'collect_input'
  | 'confirm_triage'
  | 'triage_loading'
  | 'triage_ready'
  | 'confirm_deep_review'
  | 'deep_review_loading'
  | 'deep_review_ready'
  | 'material_handoff';

export interface OpportunityFitDraftState {
  applicationId: number;
  pilotDraftKey: string;
  phase: OpportunityFitDraftPhase;
  resumeID?: number;
  jdText: string;
  assertionsText: string;
  review: OpportunityFitReview | null;
  actionError: string | null;
  triageAttemptKey: string | null;
}

export type OpportunityFitDraftErrorDisposition = 'unknown' | 'definite_no_write';

export type OpportunityFitDraftAction =
  | { type: 'set_resume'; resumeID?: number }
  | { type: 'set_jd'; jdText: string }
  | { type: 'set_assertions'; assertionsText: string }
  | { type: 'set_phase'; phase: OpportunityFitDraftPhase }
  | { type: 'set_attempt_key'; key: string | null }
  | { type: 'set_review'; review: OpportunityFitReview }
  | { type: 'set_error'; error: string; disposition: OpportunityFitDraftErrorDisposition }
  | { type: 'set_error'; error: null; disposition: null };

export interface OpportunityFitDraftStore {
  getState: () => OpportunityFitDraftState;
  dispatch: (action: OpportunityFitDraftAction) => void;
  subscribe: (listener: () => void) => () => void;
}

const OPPORTUNITY_FIT_DRAFT_PHASES: ReadonlySet<string> = new Set([
  'collect_input',
  'confirm_triage',
  'triage_loading',
  'triage_ready',
  'confirm_deep_review',
  'deep_review_loading',
  'deep_review_ready',
  'material_handoff',
]);

export function isOpportunityFitDraftPhase(value: unknown): value is OpportunityFitDraftPhase {
  return typeof value === 'string' && OPPORTUNITY_FIT_DRAFT_PHASES.has(value);
}

export function createInitialOpportunityFitDraft(
  applicationId: number,
  pilotDraftKey: string,
): OpportunityFitDraftState {
  return {
    applicationId,
    pilotDraftKey,
    phase: 'collect_input',
    resumeID: undefined,
    jdText: '',
    assertionsText: '',
    review: null,
    actionError: null,
    triageAttemptKey: null,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isOptionalNumber(value: unknown): value is number | undefined {
  return value === undefined || (typeof value === 'number' && Number.isFinite(value));
}

function isOpportunityFitRecommendation(value: unknown): value is OpportunityFitReview['recommendation'] {
  return value === 'advance' || value === 'hold' || value === 'decline';
}

function isValidOpportunityFitReview(value: unknown): value is OpportunityFitReview {
  if (!isRecord(value)) {
    return false;
  }

  const source = value.source;
  const triage = value.triage;
  return (
    typeof value.id === 'number'
    && Number.isFinite(value.id)
    && typeof value.application_id === 'number'
    && Number.isFinite(value.application_id)
    && (value.resume_id === null || (typeof value.resume_id === 'number' && Number.isFinite(value.resume_id)))
    && (value.status === 'triage_complete' || value.status === 'deep_reviewed')
    && isOpportunityFitRecommendation(value.recommendation)
    && isRecord(value.summary)
    && isRecord(source)
    && isRecord(source.application)
    && isRecord(source.resume)
    && isRecord(source.jd)
    && Array.isArray(source.candidate_assertions)
    && isRecord(triage)
    && isRecord(triage.summary)
    && isOpportunityFitRecommendation(triage.recommendation)
    && Array.isArray(triage.hard_constraints)
    && Array.isArray(triage.fit_signals)
    && Array.isArray(triage.gaps)
    && isRecord(triage.deadline)
    && Array.isArray(triage.next_questions)
    && (value.deep_review === null || isRecord(value.deep_review))
  );
}

function isValidOpportunityFitDraftState(value: unknown): value is OpportunityFitDraftState {
  if (!isRecord(value)) {
    return false;
  }

  return (
    typeof value.applicationId === 'number'
    && Number.isFinite(value.applicationId)
    && typeof value.pilotDraftKey === 'string'
    && isOpportunityFitDraftPhase(value.phase)
    && isOptionalNumber(value.resumeID)
    && typeof value.jdText === 'string'
    && typeof value.assertionsText === 'string'
    && (value.review === null || isRecord(value.review))
    && (value.actionError === null || typeof value.actionError === 'string')
    && (value.triageAttemptKey === null || typeof value.triageAttemptKey === 'string')
  );
}

function isValidOpportunityFitDraftAction(action: OpportunityFitDraftAction): boolean {
  if (!isRecord(action) || typeof action.type !== 'string') {
    return false;
  }

  switch (action.type) {
    case 'set_resume':
      return isOptionalNumber(action.resumeID);
    case 'set_jd':
      return typeof action.jdText === 'string';
    case 'set_assertions':
      return typeof action.assertionsText === 'string';
    case 'set_phase':
      return isOpportunityFitDraftPhase(action.phase);
    case 'set_attempt_key':
      return action.key === null || typeof action.key === 'string';
    case 'set_review':
      return isValidOpportunityFitReview(action.review);
    case 'set_error':
      return action.error === null
        ? action.disposition === null
        : (action.disposition === 'unknown' || action.disposition === 'definite_no_write');
    default:
      return false;
  }
}

export function classifyOpportunityFitFailure(
  failure: unknown,
): OpportunityFitDraftErrorDisposition {
  if (!isRecord(failure) || !isRecord(failure.response)) {
    return 'unknown';
  }

  const response = failure.response;
  if (response.status === 422 || response.status === 404) {
    return 'definite_no_write';
  }

  if (response.status !== 502 || !isRecord(response.data)) {
    return 'unknown';
  }

  return response.data.error_code === 'opportunity_fit_provider_error'
    || response.data.error_code === 'opportunity_fit_unverifiable'
    ? 'definite_no_write'
    : 'unknown';
}

type OpportunityFitDraftInputField = 'resumeID' | 'jdText' | 'assertionsText';

function updateDraftInput(
  state: OpportunityFitDraftState,
  field: OpportunityFitDraftInputField,
  value: OpportunityFitDraftState[OpportunityFitDraftInputField],
): OpportunityFitDraftState {
  return { ...state, [field]: value, triageAttemptKey: null };
}

export function opportunityFitDraftReducer(
  state: OpportunityFitDraftState,
  action: OpportunityFitDraftAction,
): OpportunityFitDraftState {
  if (!isValidOpportunityFitDraftState(state) || !isValidOpportunityFitDraftAction(action)) {
    return state;
  }

  switch (action.type) {
    case 'set_resume':
      if (state.resumeID === action.resumeID) {
        return state;
      }
      return updateDraftInput(state, 'resumeID', action.resumeID);
    case 'set_jd':
      if (state.jdText === action.jdText) {
        return state;
      }
      return updateDraftInput(state, 'jdText', action.jdText);
    case 'set_assertions':
      if (state.assertionsText === action.assertionsText) {
        return state;
      }
      return updateDraftInput(state, 'assertionsText', action.assertionsText);
    case 'set_phase':
      if (state.phase === action.phase) {
        return state;
      }
      return { ...state, phase: action.phase };
    case 'set_attempt_key':
      if (state.triageAttemptKey === action.key) {
        return state;
      }
      return { ...state, triageAttemptKey: action.key };
    case 'set_review':
      return {
        ...state,
        phase: action.review.deep_review === null ? 'triage_ready' : 'deep_review_ready',
        review: action.review,
        actionError: null,
        triageAttemptKey: null,
      };
    case 'set_error':
      if (
        state.actionError === action.error
        && (action.disposition !== 'definite_no_write' || state.triageAttemptKey === null)
      ) {
        return state;
      }
      return {
        ...state,
        actionError: action.error,
        triageAttemptKey: action.disposition === 'definite_no_write'
          ? null
          : state.triageAttemptKey,
      };
    default:
      return assertNever(action);
  }
}

function assertNever(value: never): never {
  throw new Error(`Unexpected OpportunityFitDraftAction: ${String(value)}`);
}

export function createOpportunityFitDraftStore(
  applicationId: number,
  pilotDraftKey: string,
): OpportunityFitDraftStore {
  let state = createInitialOpportunityFitDraft(applicationId, pilotDraftKey);
  const listeners = new Set<() => void>();

  return {
    getState: () => state,
    dispatch: (action) => {
      const nextState = opportunityFitDraftReducer(state, action);
      if (nextState === state) {
        return;
      }
      state = nextState;
      listeners.forEach((listener) => listener());
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
