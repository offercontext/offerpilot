import { describe, expect, it } from 'vitest';
import kanbanCard from './KanbanBoard/KanbanCard.tsx?raw';
import applicationList from './ApplicationListView.tsx?raw';
import applicationDetail from './ApplicationDetail.tsx?raw';

describe('application Pilot entry contract', () => {
  it('exposes Ask Pilot from card, list, and detail', () => {
    expect(kanbanCard).toContain('问 Pilot');
    expect(applicationList).toContain('问 Pilot');
    expect(applicationDetail).toContain('问 Pilot');
  });
});
