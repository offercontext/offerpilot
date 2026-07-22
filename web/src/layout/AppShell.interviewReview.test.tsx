import { describe, expect, it } from 'vitest';
import appShellSource from './AppShell.tsx?raw';
import pilotCardSource from '@/features/pilot/PilotOpportunityFitCard.tsx?raw';

describe('Pilot interview review navigation', () => {
  it('keeps the entry in Application context and focuses the native review flow', () => {
    expect(pilotCardSource).toContain('onOpenInterviewReview');
    expect(pilotCardSource).toContain('打开面试复盘');
    expect(appShellSource).toContain('pilotInterviewReviewApplicationId');
    expect(appShellSource).toContain('onPilotInterviewReviewFocusConsumed');
    expect(appShellSource).toContain('onOpenInterviewReview');
  });

  it('does not make Pilot call proposal APIs or create cross-domain writes', () => {
    expect(pilotCardSource).not.toContain('createInterviewReviewProposal');
    expect(pilotCardSource).not.toContain('createNote');
    expect(pilotCardSource).not.toContain('createEvent');
    expect(appShellSource).not.toContain('writeInterviewReviewProposal');
  });
});
