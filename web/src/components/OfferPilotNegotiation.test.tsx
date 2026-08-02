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

function render(offerValue: Offer | null, onPrepareOfferNegotiation: (value: Offer) => void) {
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

  it('does not show or trigger an Offer action before the user selects an Offer', () => {
    const onPrepare = vi.fn();
    ({ host, root } = render(null, onPrepare));

    expect(host.querySelector('[data-testid="pilot-prepare-offer-negotiation"]')).toBeNull();
    expect(onPrepare).not.toHaveBeenCalled();
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
