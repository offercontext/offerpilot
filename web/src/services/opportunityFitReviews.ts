import type {
  CreateOpportunityFitReviewInput,
  OpportunityFitReview,
  OpportunityFitReviewSummary,
  CreateOpportunityFitV2Input,
  OpportunityFitV2StageResponse,
  OpportunityFitV2SessionResponse,
  OpportunityFitV2SessionSummary,
} from '@/types/opportunityFitReview';
import { createApiClient } from './http';

const http = createApiClient({ baseURL: '/api', timeout: 130000 });

export async function createOpportunityFitReview(
  applicationID: number,
  input: CreateOpportunityFitReviewInput,
): Promise<OpportunityFitReview> {
  const { data } = await http.post<OpportunityFitReview>(
    `/applications/${applicationID}/opportunity-fit-reviews`,
    input,
  );
  return data;
}

export async function createOpportunityFitV2Triage(
  applicationID: number,
  input: CreateOpportunityFitV2Input,
): Promise<OpportunityFitV2StageResponse> {
  const { data } = await http.post<OpportunityFitV2StageResponse>(
    `/applications/${applicationID}/opportunity-fit-reviews`,
    input,
  );
  return data;
}

export async function confirmOpportunityFitV2Triage(
  applicationID: number,
  reviewID: number,
  stageID: number,
  confirmationToken: string,
): Promise<OpportunityFitV2StageResponse> {
  const { data } = await http.post<OpportunityFitV2StageResponse>(
    `/applications/${applicationID}/opportunity-fit-reviews/${reviewID}/triage/${stageID}/confirm`,
    { confirmation_token: confirmationToken },
  );
  return data;
}

export async function createOpportunityFitV2DeepReview(
  applicationID: number,
  reviewID: number,
  input: CreateOpportunityFitV2Input & { parent_triage_stage_id: number },
): Promise<OpportunityFitV2StageResponse> {
  const { data } = await http.post<OpportunityFitV2StageResponse>(
    `/applications/${applicationID}/opportunity-fit-reviews/${reviewID}/deep-review`,
    { ...input, schema_version: 2 },
  );
  return data;
}

export async function listOpportunityFitReviews(
  applicationID: number,
): Promise<OpportunityFitReviewSummary[]> {
  const { data } = await http.get<unknown[]>(
    `/applications/${applicationID}/opportunity-fit-reviews`,
  );
  return data.filter((item): item is OpportunityFitReviewSummary => {
    if (typeof item !== 'object' || item === null) return false;
    const record = item as Record<string, unknown>;
    return record.schema_version === 1 && typeof record.id === 'number';
  });
}

export async function getOpportunityFitReview(
  applicationID: number,
  reviewID: number,
): Promise<OpportunityFitReview> {
  const { data } = await http.get<OpportunityFitReview>(
    `/applications/${applicationID}/opportunity-fit-reviews/${reviewID}`,
  );
  return data;
}

export async function createOpportunityFitDeepReview(
  applicationID: number,
  reviewID: number,
): Promise<OpportunityFitReview> {
  const { data } = await http.post<OpportunityFitReview>(
    `/applications/${applicationID}/opportunity-fit-reviews/${reviewID}/deep-review`,
  );
  return data;
}

export async function listOpportunityFitV2Reviews(
  applicationID: number,
): Promise<OpportunityFitV2SessionSummary[]> {
  const { data } = await http.get<unknown[]>(
    `/applications/${applicationID}/opportunity-fit-reviews`,
  );
  return data.filter((item): item is OpportunityFitV2SessionSummary => {
    if (typeof item !== 'object' || item === null) return false;
    const record = item as Record<string, unknown>;
    return record.schema_version === 2
      && typeof record.review_id === 'number'
      && typeof record.stage_count === 'number';
  });
}

export async function getOpportunityFitV2Review(
  applicationID: number,
  reviewID: number,
): Promise<OpportunityFitV2SessionResponse> {
  const { data } = await http.get<OpportunityFitV2SessionResponse>(
    `/applications/${applicationID}/opportunity-fit-reviews/${reviewID}`,
    { params: { schema_version: 2 } },
  );
  return data;
}

export async function findOpportunityFitV2SourceConflictStage(
  applicationID: number,
  stage: 'triage' | 'deep_review',
  idempotencyKey: string,
  reviewID?: number,
): Promise<OpportunityFitV2SourceConflictLookup> {
  let summaries: OpportunityFitV2SessionSummary[] = [];
  try {
    summaries = reviewID === undefined ? await listOpportunityFitV2Reviews(applicationID) : [];
  } catch {
    return { status: 'unknown' };
  }
  const reviewIDs = reviewID === undefined
    ? summaries
      .filter((summary) => (
        summary.triage_idempotency_key === idempotencyKey
        || summary.latest_stage?.idempotency_key === idempotencyKey
      ))
      .map((summary) => summary.review_id)
    : [reviewID];

  for (const currentReviewID of reviewIDs) {
    let session: OpportunityFitV2SessionResponse;
    try {
      session = await getOpportunityFitV2Review(applicationID, currentReviewID);
    } catch {
      return { status: 'unknown' };
    }
    const conflict = session.stages.find((item) => (
      item.stage === stage
      && item.idempotency_key === idempotencyKey
      && item.stage_status === 'source_conflict'
    ));
    if (conflict) return { status: 'found', stage: conflict };
  }
  return { status: 'not_found' };
}

export type OpportunityFitV2SourceConflictLookup =
  | { status: 'found'; stage: OpportunityFitV2StageResponse }
  | { status: 'not_found' }
  | { status: 'unknown' };
