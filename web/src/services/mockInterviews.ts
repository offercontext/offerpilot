import type {
  MockInterviewAttemptResponse,
  MockInterviewHistoryItem,
  MockInterviewProposalResponse,
  MockInterviewPendingResponse,
} from '@/types/mockInterview';
import { createApiClient } from './http';

const http = createApiClient({ baseURL: '/api' });

function base(applicationId: number, eventId: number): string {
  return `/applications/${applicationId}/events/${eventId}/mock-interview/attempts`;
}

export async function discardMockInterviewAttempt(input: {
  applicationId: number;
  eventId: number;
  attemptId: number;
}): Promise<void> {
  await http.delete(`${base(input.applicationId, input.eventId)}/${input.attemptId}`);
}

export async function startMockInterview(input: {
  applicationId: number;
  eventId: number;
  resumeId: number;
  jdVersionId: number;
  attemptKey: string;
  questionKey: string;
  preparationProposalId?: number;
  preparationItemIds?: string[];
}): Promise<MockInterviewAttemptResponse | MockInterviewPendingResponse> {
  const { data } = await http.post<MockInterviewAttemptResponse | MockInterviewPendingResponse>(base(input.applicationId, input.eventId), {
    resume_id: input.resumeId,
    jd_version_id: input.jdVersionId,
    attempt_idempotency_key: input.attemptKey,
    initial_question_idempotency_key: input.questionKey,
    preparation_proposal_id: input.preparationProposalId,
    preparation_selection: input.preparationProposalId && input.preparationItemIds?.length
      ? { proposal_id: input.preparationProposalId, item_ids: input.preparationItemIds }
      : undefined,
  });
  return data;
}

export async function generateMockInterviewQuestion(input: {
  applicationId: number;
  eventId: number;
  attemptId: number;
  turnNo: number;
  questionKey: string;
}): Promise<MockInterviewAttemptResponse | MockInterviewPendingResponse> {
  const { data } = await http.post<MockInterviewAttemptResponse | MockInterviewPendingResponse>(
    `${base(input.applicationId, input.eventId)}/${input.attemptId}/turns/${input.turnNo}/question`,
    { question_idempotency_key: input.questionKey },
  );
  return data;
}

export async function submitMockInterviewAnswer(input: {
  applicationId: number;
  eventId: number;
  attemptId: number;
  turnNo: number;
  answerText: string;
  turnKey: string;
}): Promise<{ attempt_id: number; attempt_status: string; transcript_fingerprint: string }> {
  const { data } = await http.post(`${base(input.applicationId, input.eventId)}/${input.attemptId}/turns`, {
    turn_no: input.turnNo,
    answer_text: input.answerText,
    turn_idempotency_key: input.turnKey,
  });
  return data;
}

export async function finishMockInterview(input: {
  applicationId: number;
  eventId: number;
  attemptId: number;
  feedbackKey: string;
}): Promise<MockInterviewProposalResponse | MockInterviewPendingResponse> {
  const { data } = await http.post<MockInterviewProposalResponse | MockInterviewPendingResponse>(
    `${base(input.applicationId, input.eventId)}/${input.attemptId}/finish`,
    { feedback_idempotency_key: input.feedbackKey },
  );
  return data;
}

export async function listMockInterviewHistory(applicationId: number, eventId: number): Promise<MockInterviewHistoryItem[]> {
  const { data } = await http.get<{ items: MockInterviewHistoryItem[] }>(base(applicationId, eventId));
  return data.items;
}

export async function confirmMockInterviewReviewDraft(input: {
  applicationId: number;
  eventId: number;
  attemptId: number;
  proposalId: number;
  confirmationKey: string;
  selectedBlocks: unknown[];
}) {
  const { data } = await http.post(
    `${base(input.applicationId, input.eventId)}/${input.attemptId}/review-drafts`,
    {
      proposal_id: input.proposalId,
      confirmation_idempotency_key: input.confirmationKey,
      selected_blocks: input.selectedBlocks,
    },
  );
  return data as { draft_id: number; status: string };
}
