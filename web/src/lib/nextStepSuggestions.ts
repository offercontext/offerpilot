import type { Application } from '@/types/application';
import type { ScheduleEvent } from '@/types/event';
import type { Offer } from '@/types/offer';
import type { PracticeStats } from '@/types/question';
import type { Resume } from '@/types/resume';

export type FactState<T> =
  | { status: 'known'; value: T; version?: string }
  | { status: 'unknown'; reason: 'not_loaded' | 'not_supported' | 'not_visible' };

export type ResumeFact = Resume & {
  version?: string | null;
  sha256?: string | null;
};

export interface NextStepFacts {
  application: FactState<Application>;
  availableResumes: FactState<ResumeFact[]>;
  events: FactState<ScheduleEvent[]>;
  offers: FactState<Offer[]>;
  confirmedKnowledge: FactState<unknown[]>;
  practiceStats: FactState<PracticeStats>;
  jd: FactState<string>;
  fitReview: FactState<unknown>;
  materialKit: FactState<unknown>;
  interviewPreparationHistory: FactState<unknown>;
  mockInterviewHistory: FactState<unknown>;
}

export type ApplicationDestination = {
  kind: 'application_detail';
  applicationId: number;
};

export type OpportunityFitDestination = {
  kind: 'pilot_opportunity_fit';
  applicationId: number;
};

export type MaterialKitDestination = {
  kind: 'material_kit_entry';
  applicationId: number;
};

export type InterviewEventDestination = {
  kind: 'interview_event';
  applicationId: number;
  eventId: number;
};

export type InterviewEventSelectionDestination = {
  kind: 'interview_event_selection';
  applicationId: number;
};

export type InterviewReviewDestination = {
  kind: 'interview_review';
  applicationId: number;
  eventId: number;
};

export type InterviewReviewHistoryDestination = {
  kind: 'interview_review_history';
  applicationId: number;
  eventId: number;
  reviewId: number;
};

export type InterviewReviewSelectionDestination = {
  kind: 'interview_review_selection';
  applicationId: number;
};

export type OpportunityFitHistoryDestination = {
  kind: 'opportunity_fit_history';
  applicationId: number;
  reviewId: number;
};

export type NextStepDestination =
  | ApplicationDestination
  | OpportunityFitDestination
  | MaterialKitDestination
  | InterviewEventDestination
  | InterviewEventSelectionDestination
  | InterviewReviewDestination
  | InterviewReviewHistoryDestination
  | InterviewReviewSelectionDestination
  | OpportunityFitHistoryDestination;

export type ReadonlyDestination =
  | ApplicationDestination
  | InterviewEventDestination
  | InterviewEventSelectionDestination
  | InterviewReviewDestination
  | InterviewReviewHistoryDestination
  | InterviewReviewSelectionDestination
  | OpportunityFitHistoryDestination;

export type NextStepSource = {
  label: string;
  status: 'current' | 'frozen' | 'changed' | 'unknown';
  readonlyDestination?: ReadonlyDestination;
};

export type NextStepCandidate = {
  id: string;
  stateKey: string;
  title: string;
  reason: string;
  destination: NextStepDestination;
  sources: NextStepSource[];
};

export type SourceRiskNotice = {
  id: string;
  stateKey: string;
  title: string;
  reason: string;
  sources: NextStepSource[];
  readonlyDestination?: ReadonlyDestination;
};

export type NextStepSuggestions = {
  candidates: NextStepCandidate[];
  sourceRisks: SourceRiskNotice[];
};

export type SuggestionSessionState = {
  stateKey: string;
  disposition: 'snoozed' | 'ignored';
};

export type SuggestionContext = 'workbench' | 'detail';

export function deriveNextStepSuggestions(
  _facts: NextStepFacts,
  _context: SuggestionContext,
  _now: Date,
): NextStepSuggestions {
  return { candidates: [], sourceRisks: [] };
}
