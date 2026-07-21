import type {
  CreateOpportunityFitReviewInput,
  OpportunityFitReview,
  OpportunityFitReviewSummary,
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
