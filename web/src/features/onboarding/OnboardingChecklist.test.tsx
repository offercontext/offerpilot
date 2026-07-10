import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import OnboardingChecklist from './OnboardingChecklist';

describe('OnboardingChecklist', () => {
  it('shows all four milestones and progress', () => {
    const html = renderToStaticMarkup(
      <OnboardingChecklist
        status={{
          steps: {
            configure_ai: true,
            create_primary_resume: false,
            create_first_application: false,
            send_first_pilot_message: false,
          },
          completed_count: 1,
          is_complete: false,
          force_open: false,
        }}
        onCollapse={vi.fn()}
      />,
    );
    expect(html).toContain('1 / 4');
    expect(html).toContain('配置 AI');
    expect(html).toContain('创建主简历');
    expect(html).toContain('添加第一条投递');
    expect(html).toContain('向 Pilot 发出第一条消息');
  });
});
