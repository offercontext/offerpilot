import axios from 'axios';
import type { Offer, OfferInput } from '@/types/offer';

const http = axios.create({ baseURL: '/api', timeout: 10000 });

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
