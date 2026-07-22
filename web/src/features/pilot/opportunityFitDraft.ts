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

export type OpportunityFitDraftAction =
  | { type: 'set_resume'; resumeID?: number }
  | { type: 'set_jd'; jdText: string }
  | { type: 'set_assertions'; assertionsText: string }
  | { type: 'set_phase'; phase: OpportunityFitDraftPhase }
  | { type: 'set_attempt_key'; key: string | null }
  | { type: 'set_review'; review: OpportunityFitReview }
  | { type: 'set_error'; error: string | null };

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
      return isRecord(action.review);
    case 'set_error':
      return action.error === null || typeof action.error === 'string';
    default:
      return false;
  }
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
      if (state.actionError === action.error) {
        return state;
      }
      return { ...state, actionError: action.error };
  }
}
