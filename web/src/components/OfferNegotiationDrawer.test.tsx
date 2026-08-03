// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import OfferNegotiationDrawer, { type OfferNegotiationDraft } from './OfferNegotiationDrawer';
import type { Offer, OfferNegotiationProposal, OfferNegotiationPreview } from '@/types/offer';
import { OfferNegotiationError } from '@/services/offers';

const service = vi.hoisted(() => ({
  create: vi.fn(),
  list: vi.fn(async (): Promise<any[]> => []),
  dimensions: vi.fn(async (): Promise<any[]> => []),
  values: vi.fn(async () => []),
  confirm: vi.fn(),
  preview: vi.fn(),
}));

vi.mock('@/services/offers', () => ({
  createOfferNegotiationProposal: service.create,
  listOfferNegotiationProposals: service.list,
  listOfferComparisonDimensions: service.dimensions,
  listOfferComparisonValues: service.values,
  confirmOfferNegotiationProposal: service.confirm,
  previewOfferNegotiation: service.preview,
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
  input_snapshot: {
    snapshot_version: 1,
    offer_snapshot: {
      company_name: 'Company', position_name: 'Engineer', status: 'pending',
      base_monthly: 28000, months_per_year: 12, signing_bonus: 0,
      equity: null, perks: null, deadline: null, notes: null,
      dimensions: [{ path_id: 'dimension_001', label: '通勤', value_text: '地铁 35 分钟' }],
    },
    user_brief: { goal: 'Goal', concerns: 'Concern', scenario: 'Call' },
  },
});

const preview = (): OfferNegotiationPreview => ({
  source_fingerprint: 'fingerprint',
  snapshot: proposal().input_snapshot,
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
    service.preview.mockReset();
    service.preview.mockResolvedValue(preview());
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

  it('does not loop when the parent stores each draft update', async () => {
    let renderCount = 0;
    function Wrapper() {
      const [draft, setDraft] = useState<OfferNegotiationDraft | null>(null);
      renderCount += 1;
      return <OfferNegotiationDrawer open offer={offer} draft={draft ?? undefined} onClose={vi.fn()} onDraftChange={setDraft} />;
    }
    await act(async () => { root?.render(<Wrapper />); });
    expect(renderCount).toBeLessThan(6);
  });

  it('requires a non-blank concerns field before generation', async () => {
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={offer} onClose={vi.fn()} />); });
    const inputs = host?.querySelectorAll('input') ?? [];
    const textareas = host?.querySelectorAll('textarea') ?? [];
    await act(async () => {
      changeValue(inputs[0] as HTMLInputElement, 'Goal');
      changeValue(textareas[0] as HTMLTextAreaElement, ' \t');
      changeValue(inputs[1] as HTMLInputElement, 'Call');
    });
    expect(host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.disabled).toBe(true);
    expect(service.create).not.toHaveBeenCalled();
  });

  it('uses the frozen dimension ids when creating a proposal', async () => {
    service.create.mockResolvedValue(proposal());
    service.dimensions.mockResolvedValueOnce([
      { id: 9, label: '成长空间', archived_at: null },
      { id: 3, label: '通勤', archived_at: null },
    ]);
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={offer} dimensionIds={[9, 3]} onClose={vi.fn()} />); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    const inputs = host?.querySelectorAll('input') ?? [];
    const textareas = host?.querySelectorAll('textarea') ?? [];
    await act(async () => {
      changeValue(inputs[0] as HTMLInputElement, 'Goal');
      changeValue(textareas[0] as HTMLTextAreaElement, 'Concern');
      changeValue(inputs[1] as HTMLInputElement, 'Call');
      host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.click();
    });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.click(); });
    expect(service.create.mock.calls[0][1].dimension_ids).toEqual([3, 9]);
  });

  it('blocks generation when selected dimension facts cannot be loaded', async () => {
    service.dimensions.mockRejectedValueOnce(new Error('dimension read failed'));
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={offer} dimensionIds={[3]} onClose={vi.fn()} />); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    const inputs = host?.querySelectorAll('input') ?? [];
    const textareas = host?.querySelectorAll('textarea') ?? [];
    await act(async () => {
      changeValue(inputs[0] as HTMLInputElement, 'Goal');
      changeValue(textareas[0] as HTMLTextAreaElement, 'Concern');
      changeValue(inputs[1] as HTMLInputElement, 'Call');
    });
    expect(host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.disabled).toBe(true);
    expect(service.create).not.toHaveBeenCalled();
  });

  it('shows the complete frozen Offer facts before generation', async () => {
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={{ ...offer, equity: '期权', perks: '补充医疗', deadline: '周五', notes: '用户备注' }} onClose={vi.fn()} />); });
    expect(host?.querySelector('[data-testid="offer-negotiation-input-facts"]')?.textContent).toContain('期权');
    expect(host?.querySelector('[data-testid="offer-negotiation-input-facts"]')?.textContent).toContain('用户备注');
  });

  it('renders history from the proposal snapshot rather than the current Offer', async () => {
    service.list.mockResolvedValue([proposal()]);
    await act(async () => {
      root?.render(
        <OfferNegotiationDrawer
          open
          offer={{ ...offer, company_name: 'Current company', equity: 'Current equity', perks: 'Current perks', deadline: 'Current deadline', notes: 'Current notes' }}
          onClose={vi.fn()}
        />,
      );
    });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    await act(async () => { host?.querySelector<HTMLButtonElement>('section[aria-label="历史谈薪准备"] button')?.click(); });
    const facts = host?.querySelector('[data-testid="offer-negotiation-input-facts"]')?.textContent ?? '';
    expect(facts).toContain('Company');
    expect(facts).not.toContain('Current company');
    expect(facts).not.toContain('Current equity');
    expect(facts).not.toContain('Current perks');
    expect(facts).not.toContain('Current deadline');
    expect(facts).not.toContain('Current notes');
    expect(facts).toContain('Goal');
    expect(facts).toContain('Concern');
    expect(facts).toContain('Call');
    expect(facts).toContain('通勤');
    expect(facts).toContain('地铁 35 分钟');
  });

  it('generates an editable evidence-backed draft and confirms selected blocks', async () => {
    service.create.mockResolvedValue(proposal());
    service.confirm.mockResolvedValue({
      id: 8,
      proposal_id: 3,
      offer_id: 7,
      selected_blocks: ['goal-1'],
      edited_content: { blocks: proposal().proposal.communication_goals, edits: { 'goal-1': '用户最终编辑的表达' }, proposal_hash: 'hash' },
      content_hash: 'brief-hash',
      confirmed_at: '2026-08-01T00:00:00Z',
    });
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
    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.click(); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    const checkbox = host?.querySelector('article input[type="checkbox"]') as HTMLInputElement;
    await act(async () => { checkbox.click(); });
    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-confirm"]')?.click(); });
    expect(host?.querySelector('[aria-label="确认保存谈薪准备"]')).not.toBeNull();
    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-action="confirm-save"]')?.click(); });
    expect(service.confirm).toHaveBeenCalledTimes(1);
    expect(service.confirm.mock.calls[0][0]).toBe(3);
    expect(service.confirm.mock.calls[0][1].selected_blocks).toEqual(['goal-1']);
    expect(service.create.mock.calls[0][2]).toBe('ui');
    expect(host?.textContent).toContain('用户最终编辑的表达');
  });

  it('uses the product confirmation panel without changing request order', async () => {
    const nativeConfirm = window.confirm;
    service.create.mockResolvedValue(proposal());
    await act(async () => { root?.render(<OfferNegotiationDrawer open offer={offer} onClose={vi.fn()} />); });
    const inputs = host?.querySelectorAll('input') ?? [];
    const textareas = host?.querySelectorAll('textarea') ?? [];
    await act(async () => {
      changeValue(inputs[0] as HTMLInputElement, '确认薪资结构');
      changeValue(textareas[0] as HTMLTextAreaElement, '远程安排');
      changeValue(inputs[1] as HTMLInputElement, '电话沟通');
      host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.click();
    });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(service.preview).toHaveBeenCalledTimes(1);
    expect(service.create).not.toHaveBeenCalled();
    expect(host?.querySelector('[aria-label="确认本次 AI 输入"]')).not.toBeNull();
    expect(window.confirm).toBe(nativeConfirm);

    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-action="confirm-generate"]')?.click(); });
    expect(service.create).toHaveBeenCalledTimes(1);
    expect(window.confirm).toBe(nativeConfirm);
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
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.click(); });
    expect(service.create.mock.calls[0][2]).toBe('pilot');
  });

  it.each([
    ['provider error', new OfferNegotiationError(502, 'offer_negotiation_provider_error')],
    ['bare 5xx', new OfferNegotiationError(502, null)],
  ])('keeps %s input frozen and exposes retry', async (_label, error) => {
    service.create.mockRejectedValueOnce(error);
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
    await act(async () => { host?.querySelector<HTMLButtonElement>('[data-testid="offer-negotiation-generate"]')?.click(); });
    expect(host?.querySelector('fieldset')?.hasAttribute('disabled')).toBe(true);
    expect(service.create).toHaveBeenCalledTimes(1);
  });
});
