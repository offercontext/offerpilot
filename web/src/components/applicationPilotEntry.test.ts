import { describe, expect, it } from 'vitest';
import kanbanCard from './KanbanBoard/KanbanCard.tsx?raw';
import applicationList from './ApplicationListView.tsx?raw';
import applicationDetail from './ApplicationDetail.tsx?raw';
import offerCard from './OfferCard.tsx?raw';
import resumeCard from './ResumeCard.tsx?raw';

describe('application Pilot entry contract', () => {
  it('exposes an accessible Pilot attachment action for applications, offers, and resumes', () => {
    expect(applicationDetail).toContain('PilotAttachmentHandle');
    expect(applicationList).toContain('PilotAttachmentHandle');
    expect(kanbanCard).toContain('onAttachToPilot');
    expect(offerCard).toContain("kind: 'offer'");
    expect(resumeCard).toContain("kind: 'resume'");
  });
});
