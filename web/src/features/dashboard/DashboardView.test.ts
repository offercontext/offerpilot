import { describe, expect, it } from 'vitest';
import source from './DashboardView.tsx?raw';

describe('DashboardView onboarding actions', () => {
  it('forwards typed onboarding actions to the checklist', () => {
    expect(source).toContain('onOnboardingAction: (action: OnboardingAction) => void;');
    expect(source).toContain('onAction={onOnboardingAction}');
  });
});
