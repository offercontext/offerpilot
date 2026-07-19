// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MaterialRevisionProposal } from '@/types/materialRevisionProposal';

const proposalService = vi.hoisted(() => ({
  acceptMaterialRevisionProposal: vi.fn(),
  rejectMaterialRevisionProposal: vi.fn(),
}));

vi.mock('@/services/materialRevisionProposals', () => proposalService);
vi.mock('antd', () => ({
  Alert: ({ message }: any) => <div role="alert">{message}</div>,
  Button: ({ children, ...props }: any) => <button type="button" {...props}>{children}</button>,
  Checkbox: ({ checked, onChange, ...props }: any) => (
    <input type="checkbox" checked={checked} onChange={(event) => onChange?.({ target: { checked: event.target.checked } })} {...props} />
  ),
  Modal: ({ open, title, children, footer, onOk, okText, cancelText }: any) => open ? (
    <section role="dialog" aria-label={title}>
      <h2>{title}</h2>
      {children}
      {footer}
      {onOk ? <button type="button" onClick={onOk}>{okText}</button> : null}
      {onOk ? <button type="button">{cancelText}</button> : null}
    </section>
  ) : null,
  Space: ({ children }: any) => <div>{children}</div>,
  Tag: ({ children }: any) => <span>{children}</span>,
  Typography: {
    Paragraph: ({ children }: any) => <p>{children}</p>,
    Text: ({ children }: any) => <span>{children}</span>,
  },
}));

const { default: MaterialProposalReviewModal } = await import('./MaterialProposalReviewModal');

const proposal: MaterialRevisionProposal = {
  id: 3,
  application_id: 7,
  material_kit_id: 5,
  source_resume_id: 11,
  status: 'draft',
  summary: 'Tailor backend experience.',
  proposal_sha256: 'abc',
  result_resume_id: null,
  created_at: '2026-07-15T00:00:00Z',
  changes: [{
    id: 'change-fastapi',
    path: '/experience/0/highlights/0',
    before: 'Built APIs',
    after: 'Built FastAPI APIs',
    rationale: 'Make the existing API experience specific.',
    evidence_refs: [{ source: 'resume', path: '/experience/0/highlights/0', excerpt: 'Built APIs' }],
  }],
  source: {
    application: { id: 7, company_name: 'Acme', position_name: 'Backend' },
    material_kit: { id: 5, jd_excerpt: 'FastAPI backend' },
    resume: { id: 11, title: 'Backend Resume' },
    latest_evidence_bundle: null,
    user_assertions: [{ id: 'assertion-1', text: 'I led the migration.' }],
  },
  accepted_change_ids: [],
  accepted_at: null,
  rejected_at: null,
};

let root: Root | undefined;
let container: HTMLDivElement | undefined;

function render() {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root?.render(
    <MaterialProposalReviewModal
      applicationID={7}
      proposal={proposal}
      open
      onClose={vi.fn()}
      onAccepted={vi.fn()}
    />,
  ));
  return container;
}

function button(view: HTMLDivElement, label: string) {
  return [...view.querySelectorAll('button')].find((item) => item.textContent?.includes(label)) as HTMLButtonElement;
}

beforeEach(() => {
  proposalService.acceptMaterialRevisionProposal.mockReset();
  proposalService.rejectMaterialRevisionProposal.mockReset();
  proposalService.acceptMaterialRevisionProposal.mockResolvedValue({});
  proposalService.rejectMaterialRevisionProposal.mockResolvedValue({});
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

describe('MaterialProposalReviewModal', () => {
  it('shows evidence, user assertion labels, and selects all changes by default', () => {
    const view = render();

    expect(view.textContent).toContain('AI recommendation — human review required');
    expect(view.textContent).toContain('Built APIs');
    expect(view.textContent).toContain('User assertion supplied for this proposal');
    expect(view.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
    expect(button(view, 'Accept selected changes')?.disabled).toBe(false);
  });

  it('requires a second confirmation and sends selected ids and proposal hash', async () => {
    const view = render();
    const checkbox = view.querySelector<HTMLInputElement>('input[type="checkbox"]');
    act(() => checkbox?.click());
    expect(button(view, 'Accept selected changes')?.disabled).toBe(true);

    act(() => checkbox?.click());
    act(() => button(view, 'Accept selected changes')?.click());
    expect(view.textContent).toContain('This will create a new derived Resume version');
    await act(async () => button(view, 'Create derived resume')?.click());

    expect(proposalService.acceptMaterialRevisionProposal).toHaveBeenCalledWith(7, 3, {
      expected_proposal_sha256: 'abc',
      selected_change_ids: ['change-fastapi'],
    });
  });

  it('rejects without calling accept', async () => {
    const view = render();
    await act(async () => button(view, 'Reject proposal')?.click());

    expect(proposalService.rejectMaterialRevisionProposal).toHaveBeenCalledWith(7, 3);
    expect(proposalService.acceptMaterialRevisionProposal).not.toHaveBeenCalled();
  });

  it('disables stale acceptance after a source conflict', async () => {
    proposalService.acceptMaterialRevisionProposal.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 409 },
    });
    const view = render();
    act(() => button(view, 'Accept selected changes')?.click());
    await act(async () => button(view, 'Create derived resume')?.click());

    expect(view.textContent).toContain('The source changed while this proposal was open');
    expect(button(view, 'Accept selected changes')?.disabled).toBe(true);
  });
});
