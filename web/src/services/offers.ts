import type {
  Offer,
  OfferComparisonDimension,
  OfferComparisonRead,
  OfferComparisonValue,
  OfferInput,
} from '@/types/offer';
import { createApiClient } from './http';

const http = createApiClient({ baseURL: '/api', timeout: 10000 });

export async function listOffers(status?: string): Promise<Offer[]> {
  const { data } = await http.get<Offer[]>('/offers', { params: status ? { status } : {} });
  return data ?? [];
}

export async function getOffer(id: number): Promise<Offer> {
  const { data } = await http.get<Offer>(`/offers/${id}`);
  return data;
}

export async function createOffer(input: OfferInput): Promise<Offer> {
  const { data } = await http.post<Offer>('/offers', input);
  return data;
}

export async function updateOffer(id: number, input: OfferInput): Promise<Offer> {
  const { data } = await http.put<Offer>(`/offers/${id}`, input);
  return data;
}

export async function deleteOffer(id: number): Promise<void> {
  await http.delete(`/offers/${id}`);
}

export async function compareOffers(ids: number[]): Promise<Offer[]> {
  const { data } = await http.get<Offer[]>('/offers/compare', { params: { ids: ids.join(',') } });
  return data ?? [];
}

export async function listOfferComparisonDimensions(
  includeArchived = false,
): Promise<OfferComparisonDimension[]> {
  const { data } = await http.get<OfferComparisonDimension[]>('/offers/comparison-dimensions', {
    params: includeArchived ? { include_archived: true } : {},
  });
  return data ?? [];
}

export async function createOfferComparisonDimension(label: string): Promise<OfferComparisonDimension> {
  const { data } = await http.post<OfferComparisonDimension>('/offers/comparison-dimensions', { label });
  return data;
}

export async function updateOfferComparisonDimension(
  id: number,
  input: { label?: string; archived?: boolean },
): Promise<OfferComparisonDimension> {
  const { data } = await http.patch<OfferComparisonDimension>(
    `/offers/comparison-dimensions/${id}`,
    input,
  );
  return data;
}

export async function listOfferComparisonValues(offerId: number): Promise<OfferComparisonValue[]> {
  const { data } = await http.get<OfferComparisonValue[]>(
    `/offers/${offerId}/comparison-values`,
  );
  return data ?? [];
}

export async function saveOfferComparisonValue(
  offerId: number,
  dimensionId: number,
  valueText: string,
): Promise<OfferComparisonValue> {
  const { data } = await http.put<OfferComparisonValue>(
    `/offers/${offerId}/comparison-values/${dimensionId}`,
    { value_text: valueText },
  );
  return data;
}

export async function clearOfferComparisonValue(
  offerId: number,
  dimensionId: number,
): Promise<void> {
  await http.delete(`/offers/${offerId}/comparison-values/${dimensionId}`);
}

export async function readOfferComparison(
  offerIds: number[],
  dimensionIds: number[] = [],
): Promise<OfferComparisonRead> {
  const { data } = await http.get<OfferComparisonRead>('/offers/comparison', {
    params: {
      ids: offerIds.join(','),
      ...(dimensionIds.length > 0 ? { dimension_ids: dimensionIds.join(',') } : {}),
    },
  });
  return data;
}
