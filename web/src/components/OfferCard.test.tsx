// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Offer } from '@/types/offer';
import OfferCard from './OfferCard';

const offer: Offer = {
  id: 7,
  company_name: '星云数据',
  position_name: '后端工程师',
  status: 'pending',
  base_monthly: 28000,
  months_per_year: 12,
  signing_bonus: 0,
  equity: '',
  perks: '补充医疗、弹性办公',
  deadline: '2026-08-15',
  notes: '筱哲｜一线业务平台方向',
  assessment: '',
  total_cash: 336000,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

describe('OfferCard', () => {
  let root: Root | null = null;
  let host: HTMLDivElement | null = null;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    root = null;
    host = null;
  });

  it('renders preparation as the primary action without replacing the coach', () => {
    const onNegotiation = vi.fn();
    const onCoach = vi.fn();
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);

    act(() => {
      root?.render(
        <OfferCard
          offer={offer}
          selected={false}
          onToggleSelect={vi.fn()}
          onCoach={onCoach}
          onNegotiation={onNegotiation}
          onView={vi.fn()}
        />,
      );
    });

    const prepare = host.querySelector<HTMLButtonElement>('[data-action="start-negotiation"]');
    const coach = host.querySelector<HTMLButtonElement>('[data-action="open-negotiation-coach"]');
    expect(host.querySelector('input[aria-label]')?.getAttribute('aria-label')).toContain('星云数据');
    expect(prepare?.textContent).toContain('开始谈薪准备');
    expect(prepare?.className).toContain('ant-btn-primary');
    expect(coach?.textContent).toContain('谈薪教练');
    expect(host.textContent).toContain('星云数据');
    expect(host.textContent).toContain('后端工程师');
    expect(host.textContent).toContain('28K');
    expect(host.textContent).toContain('签字费 0.0万');
    expect(host.textContent).not.toContain('签字费 无');
    expect(host.textContent).toContain('截止 2026-08-15');
    expect(host.querySelector('[data-action="view-offer"]')).not.toBeNull();

    act(() => prepare?.click());
    expect(onNegotiation).toHaveBeenCalledWith(offer);
    expect(onCoach).not.toHaveBeenCalled();
  });

  it('keeps the coach action explicit when preparation is unavailable', () => {
    const onCoach = vi.fn();
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root?.render(
        <OfferCard offer={offer} selected onToggleSelect={vi.fn()} onCoach={onCoach} onView={vi.fn()} />,
      );
    });
    expect(host!.querySelector('[data-action="start-negotiation"]')).toBeNull();
    act(() => host!.querySelector<HTMLButtonElement>('[data-action="open-negotiation-coach"]')?.click());
    expect(onCoach).toHaveBeenCalledWith(offer);
  });
});
