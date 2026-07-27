// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Offer } from '@/types/offer';
import OfferCenterView from './OfferCenterView';

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: () => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }),
});

const queryState = vi.hoisted(() => ({ offers: [] as Offer[] }));
vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: queryState.offers, isError: false, isFetching: false, isLoading: false, refetch: vi.fn() }) }));
vi.mock('@/services/offers', () => ({ listOffers: vi.fn() }));
vi.mock('@/components/OfferCard', () => ({ default: () => <div /> }));
vi.mock('@/components/AddOfferForm', () => ({ default: () => null }));
vi.mock('@/components/OfferCompareDrawer', () => ({ default: () => null }));

const offer = (id: number): Offer => ({
  id, company_name: `Company ${id}`, position_name: 'Engineer', status: 'pending',
  base_monthly: 30000, months_per_year: 13, signing_bonus: 10000, equity: '', perks: '',
  deadline: '', notes: '', assessment: '', total_cash: 400000,
  created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-01T00:00:00Z',
});

describe('OfferCenterView comparison guardrails', () => {
  let root: Root | null = null;
  let host: HTMLDivElement | null = null;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    root = null;
    host = null;
  });

  it('does not show unsupported aggregate claims for any offer count', async () => {
    queryState.offers = [offer(1), offer(2)];
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root?.render(<OfferCenterView applications={[]} onCoach={vi.fn()} />); });

    expect(host.textContent).not.toContain('平均年总包');
    expect(host.textContent).not.toContain('最高签字费');
  });
});
