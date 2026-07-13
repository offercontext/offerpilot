import { describe, expect, it } from 'vitest';
import source from './ResumeLibraryView.tsx?raw';

describe('ResumeLibraryView onboarding source contract', () => {
  it('focuses the resume creation entry without creating a resume', () => {
    expect(source).toContain('onboardingFocusToken?: number;');
    expect(source).toContain('data-onboarding-target="resume-create"');
    expect(source).toContain('onboardingEntryRef.current?.focus({ preventScroll: true });');
    expect(source).not.toContain('onboardingFocusToken && createDialogMut.mutate()');
  });
});
