// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import OfferNegotiationDrawer from './OfferNegotiationDrawer';
import type { Offer, OfferNegotiationProposal } from '@/types/offer';
import { OfferNegotiationError } from '@/services/offers';

const service = vi.hoisted(() => ({
  create: vi.fn(),
  list: vi.fn(async () => []),
  confirm: vi.fn(),
}));

vi.mock('@/services/offers', () => ({
  createOfferNegotiationProposal: service.create,
  listOfferNegotiationProposals: service.list,
  confirmOfferNegotiationProposal: service.confirm,
  OfferNegotiationError: class OfferNegotiationError extends Error {
    constructor(public status: number, public code: string | null) { super(code ?? 'error'); }
  },
}));

const offer: Offer = {
  id: 7, company_name: 'Company', position_name: 'Engineer', status: 'pending',
  base_monthly: 28000, months_per_year: 12, signing_bonus: 0, equity: '', perks: '',
  deadline: '', notes: '', assessment: '', total_cash: 336000,
  created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
};

const proposal = (): OfferNegotiationProposal => ({
  id: 3, offer_id: 7, application_id: null, attempt_status: 'ready', proposal_status: 'normal',
  source_fingerprint: 'fingerprint', source_changed: false, source_states: { offer: 'current' }, proposal_hash: 'hash',
  proposal: {
    proposal_status: 'normal',
    communication_goals: [{ id: 'goal-1', text: 'Goal', rationale: 'Offer', evidence_refs: [{ source: 'offer_snapshot', path: '/offer_snapshot/company_name', excerpt: 'Company' }] }],
    clarification_questions: [], talking_points: [], preparation_checks: [],
  },
});

function changeValue(control: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype = control instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(control, value);
  control.dispatchEvent(new Event('input', { bubbles: true }));
  control.dispatchEvent(new Event('change', { bubbles: true }));
}

describe('OfferNegotiationDrawer', () => {
  let root: Root | null = null;
  let host: HTMLDivElement | null = null;

  beforeEach(() => {
    service.create.mockReset();
    service.confirm.mockReset();
    service.list.mockResolvedValue([]);
    vi.stubGlobal('confirm', vi.fn(() => true));
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    vi.unstubAllGlobals();
  });

  it('requires the three user brief fields before generation', async () => {
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={offer} onClose={vi.fn()} />); });
    const button = host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]');
    expect(button?.disabled).toBe(true);
    expect(service.create).not.toHaveBeenCalled();
  });

  it('generates an editable evidence-backed draft and confirms selected blocks', async () => {
    service.create.mockResolvedValue(proposal());
    service.confirm.mockResolvedValue({ id: 8, proposal_id: 3, offer_id: 7, selected_blocks: ['goal-1'], edited_content: {}, content_hash: 'brief-hash', confirmed_at: '2026-08-01T00:00:00Z' });
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={offer} onClose={vi.fn()} />); });
    const inputs = host?.querySelectorAll('input') ?? [];
    const textareas = host?.querySelectorAll('textarea') ?? [];
    await act(async () => {
      changeValue(inputs[0] as HTMLInputElement, 'Goal');
      changeValue(textareas[0] as HTMLTextAreaElement, 'Concern');
      changeValue(inputs[1] as HTMLInputElement, 'Call');
    });
    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.click(); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    const checkbox = host?.querySelector('article input[type="checkbox"]') as HTMLInputElement;
    await act(async () => { checkbox.click(); });
    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-confirm"]')?.click(); });
    expect(service.confirm).toHaveBeenCalledTimes(1);
    expect(service.confirm.mock.calls[0][0]).toBe(3);
    expect(service.confirm.mock.calls[0][1].selected_blocks).toEqual(['goal-1']);
    expect(service.create.mock.calls[0][2]).toBe('ui');
  });

  it('marks Pilot-generated requests without changing the API payload', async () => {
    service.create.mockResolvedValue(proposal());
    await act(async () => {
      root?.render(<OfferNegotiationDrawer open offer={offer} entrypoint="pilot" onClose={vi.fn()} />);
    });
    const inputs = host?.querySelectorAll('input') ?? [];
    const textareas = host?.querySelectorAll('textarea') ?? [];
    await act(async () => {
      changeValue(inputs[0] as HTMLInputElement, 'Goal');
      changeValue(textareas[0] as HTMLTextAreaElement, 'Concern');
      changeValue(inputs[1] as HTMLInputElement, 'Call');
      host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.click();
    });
    expect(service.create.mock.calls[0][2]).toBe('pilot');
  });

  it.each([
    ['provider error', new OfferNegotiationError(502, 'offer_negotiation_provider_error')],
    ['bare 5xx', new OfferNegotiationError(502, null)],
  ])('keeps %s input frozen and exposes retry', async (_label, error) => {
    service.create.mockRejectedValueOnce(error);
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={offer} onClose={vi.fn()} />); });
    const inputs = host?.querySelectorAll('input') ?? [];
    await act(async () => {
      changeValue(inputs[0] as HTMLInputElement, 'Goal');
      changeValue(inputs[1] as HTMLInputElement, 'Concern');
    });
    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.click(); });
    expect(host?.querySelector('fieldset')?.hasAttribute('disabled')).toBe(true);
    expect(service.create).toHaveBeenCalledTimes(1);
  });
});
