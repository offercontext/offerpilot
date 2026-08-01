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
  id: 7, company_name: '星云数据', position_name: '后端工程师', status: 'pending',
  base_monthly: 28000, months_per_year: 12, signing_bonus: 0, equity: '', perks: '',
  deadline: '', notes: '', assessment: '', total_cash: 336000,
  created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
};

const proposal = (): OfferNegotiationProposal => ({
  id: 3, offer_id: 7, application_id: null, attempt_status: 'ready', proposal_status: 'normal',
  source_fingerprint: 'fingerprint', source_changed: false, source_states: { offer: 'current' }, proposal_hash: 'hash',
  proposal: {
    proposal_status: 'normal',
    communication_goals: [{ id: 'goal-1', text: '确认入职时间', rationale: '依据 Offer', evidence_refs: [{ source: 'offer_snapshot', path: '/offer_snapshot/company_name', excerpt: '星云数据' }] }],
    clarification_questions: [], talking_points: [], preparation_checks: [],
  },
});

function changeValue(control: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(control, value);
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
    expect(host?.textContent).toContain('生成谈薪准备草稿');
    const button = Array.from(host?.querySelectorAll('button') ?? []).find((item) => item.textContent?.includes('生成谈薪准备草稿')) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(service.create).not.toHaveBeenCalled();
  });

  it('generates an editable evidence-backed draft and confirms selected blocks', async () => {
    service.create.mockResolvedValue(proposal());
    service.confirm.mockResolvedValue({ id: 8, proposal_id: 3, offer_id: 7, selected_blocks: ['goal-1'], edited_content: { blocks: [], edits: {}, proposal_hash: 'hash' }, content_hash: 'brief-hash', confirmed_at: '2026-08-01T00:00:00Z' });
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={offer} onClose={vi.fn()} />); });
    const inputs = host?.querySelectorAll('input') ?? [];
    await act(async () => {
      changeValue(inputs[0] as HTMLInputElement, '争取入职时间');
      changeValue(inputs[1] as HTMLInputElement, '电话沟通');
    });
    const generate = Array.from(host?.querySelectorAll('button') ?? []).find((item) => item.textContent?.includes('生成谈薪准备草稿')) as HTMLButtonElement;
    await act(async () => { generate.click(); });
    expect(service.create).toHaveBeenCalledTimes(1);
    expect(host?.textContent).toContain('确认入职时间');
    const checkbox = host?.querySelector('article input[type="checkbox"]') as HTMLInputElement;
    await act(async () => { checkbox.click(); });
    const confirmButton = Array.from(host?.querySelectorAll('button') ?? []).find((item) => item.textContent?.includes('确认保存谈薪准备')) as HTMLButtonElement;
    await act(async () => { confirmButton.click(); });
    expect(service.confirm).toHaveBeenCalledTimes(1);
    expect(service.confirm.mock.calls[0][0]).toBe(3);
    expect(service.confirm.mock.calls[0][1].selected_blocks).toEqual(['goal-1']);
  });

  it('keeps provider-unknown input frozen and exposes retry', async () => {
    service.create.mockRejectedValueOnce(new OfferNegotiationError(502, 'offer_negotiation_provider_error'));
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={offer} onClose={vi.fn()} />); });
    const inputs = host?.querySelectorAll('input') ?? [];
    await act(async () => {
      changeValue(inputs[0] as HTMLInputElement, '目标');
      changeValue(inputs[1] as HTMLInputElement, '电话');
    });
    const generate = Array.from(host?.querySelectorAll('button') ?? []).find((item) => item.textContent?.includes('生成谈薪准备草稿')) as HTMLButtonElement;
    await act(async () => { generate.click(); });
    expect(host?.textContent).toContain('使用原尝试重试');
    expect(host?.querySelector('fieldset')?.hasAttribute('disabled')).toBe(true);
  });
});
