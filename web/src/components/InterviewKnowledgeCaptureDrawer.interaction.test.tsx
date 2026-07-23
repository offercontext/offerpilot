import { describe, expect, it } from 'vitest';
import source from './InterviewKnowledgeCaptureDrawer.tsx?raw';

describe('InterviewKnowledgeCaptureDrawer interaction contract', () => {
  it('uses parent-owned draft state and keeps unknown results on close', () => {
    expect(source).toContain('draft: InterviewKnowledgeCaptureDraft');
    expect(source).toContain('onDraftChange');
    expect(source).toContain("draft.previewStatus === 'provider_unknown'");
    expect(source).toContain('deleteUnconfirmedInterviewKnowledgeAttempt');
    expect(source).toContain('resultUnknown');
  });
});
