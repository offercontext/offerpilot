import { describe, expect, it } from 'vitest';
import kanbanCard from './KanbanBoard/KanbanCard.tsx?raw';
import applicationList from './ApplicationListView.tsx?raw';
import applicationDetail from './ApplicationDetail.tsx?raw';
import offerCard from './OfferCard.tsx?raw';
import resumeCard from './ResumeCard.tsx?raw';

describe('application Pilot entry contract', () => {
  it('binds every supported card root directly to native Pilot attachment drag', () => {
    const cardSources = [applicationDetail, applicationList, kanbanCard, offerCard, resumeCard];

    for (const source of cardSources) {
      expect(source).toContain('createPilotAttachmentDragBinding');
      expect(source).not.toMatch(/import PilotAttachmentHandle/);
      expect(source).not.toMatch(/<PilotAttachmentHandle/);
      expect(source).not.toContain('添加到 Pilot');
    }

    expect(kanbanCard).toContain('onAttachToPilot');
    expect(offerCard).toContain("kind: 'offer'");
    expect(resumeCard).toContain("kind: 'resume'");
  });
});
