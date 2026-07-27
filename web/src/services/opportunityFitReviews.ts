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
  const { data } = await http.get<OpportunityFitReviewSummary[]>(
    `/applications/${applicationID}/opportunity-fit-reviews`,
  );
  return data;
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
