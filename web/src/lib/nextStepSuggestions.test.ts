import { describe, expect, expectTypeOf, it } from 'vitest';
import {
  deriveNextStepSuggestions,
  type InterviewReviewHistoryDestination,
  type InterviewEventSelectionDestination,
} from './nextStepSuggestions';

describe('next-step suggestion destination types', () => {
  it('exports the shared pure derivation function', () => {
    expect(deriveNextStepSuggestions).toBeTypeOf('function');
  });

  it('requires complete history and selection contexts at compile time', () => {
    const validHistory: InterviewReviewHistoryDestination = {
      kind: 'interview_review_history',
      applicationId: 1,
      eventId: 2,
      reviewId: 3,
    };
    expectTypeOf(validHistory).toMatchTypeOf<InterviewReviewHistoryDestination>();

    // @ts-expect-error review history cannot omit reviewId
    const incompleteHistory: InterviewReviewHistoryDestination = {
      kind: 'interview_review_history',
      applicationId: 1,
      eventId: 2,
    };
    void incompleteHistory;

    // @ts-expect-error a multi-event selection cannot guess an eventId
    const guessedSelection: InterviewEventSelectionDestination = {
      kind: 'interview_event_selection',
      applicationId: 1,
      eventId: 2,
    };
    void guessedSelection;
  });

  it('keeps the destination union discriminated', () => {
    expectTypeOf<InterviewReviewHistoryDestination['reviewId']>().toEqualTypeOf<number>();
    expectTypeOf<InterviewEventSelectionDestination>().not.toHaveProperty('eventId');
    expect(true).toBe(true);
  });
});
