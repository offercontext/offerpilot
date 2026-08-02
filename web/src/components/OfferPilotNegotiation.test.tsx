// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ContextPanel from './ChatPanel/ContextPanel';
import type { Offer } from '@/types/offer';

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const offer: Offer = {
  id: 42,
  application_id: 7,
  company_name: '星云数据',
  position_name: '后端工程师',
  status: 'pending',
  base_monthly: 28000,
  months_per_year: 12,
  signing_bonus: 0,
  equity: '',
  perks: '',
  deadline: '',
  notes: '',
  assessment: '',
  total_cash: 336000,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

function render(
  offerValue: Offer | null,
  onPrepareOfferNegotiation: (value: Offer) => void,
  offers: Offer[] = [offer],
) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const root: Root = createRoot(host);
  act(() => {
    root.render(
      <ContextPanel
        isNego
        offer={offerValue}
        capabilities={[]}
        evidence={[]}
        autoApprove={false}
        hasKey
        degraded={false}
        disabled={false}
        onCapability={vi.fn()}
        onToggleAutoApprove={vi.fn()}
        onPrepareOfferNegotiation={onPrepareOfferNegotiation}
        offers={offers}
        onSelectOffer={onPrepareOfferNegotiation}
      />,
    );
  });
  return { host, root };
}

describe('Pilot offer negotiation entry', () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    root = undefined;
    host = undefined;
  });

  it('opens an explicit Offer selector without chat or provider work before selection', () => {
    const onPrepare = vi.fn();
    ({ host, root } = render(null, onPrepare));

    const choose = host.querySelector<HTMLButtonElement>('[data-testid="pilot-choose-offer-negotiation"]');
    expect(choose).not.toBeNull();
    act(() => choose?.click());
    const select = host.querySelector<HTMLSelectElement>('[data-testid="pilot-offer-selector"]');
    expect(select).not.toBeNull();
    act(() => {
      select!.value = String(offer.id);
      select!.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(onPrepare).toHaveBeenCalledTimes(1);
    expect(onPrepare).toHaveBeenCalledWith(offer);
    expect(host.textContent).not.toContain('provider');
  });

  it('opens the shared Offer flow only after an explicitly selected Offer is present', () => {
    const onPrepare = vi.fn();
    ({ host, root } = render(offer, onPrepare));

    const button = host.querySelector<HTMLButtonElement>('[data-testid="pilot-prepare-offer-negotiation"]');
    expect(button).not.toBeNull();
    act(() => button?.click());
    expect(onPrepare).toHaveBeenCalledTimes(1);
    expect(onPrepare).toHaveBeenCalledWith(offer);
  });
});
