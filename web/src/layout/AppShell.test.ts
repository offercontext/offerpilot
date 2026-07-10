import { describe, expect, it } from 'vitest';
import source from './AppShell.tsx?raw';

describe('AppShell source contract', () => {
  it('closes stale application detail when a selected application disappears', () => {
    expect(source).toContain('!apps.some((app) => app.id === selected.id)');
    expect(source).toContain('setSelected(null)');
  });

  it('refreshes workspace data after Pilot writes complete', () => {
    expect(source).toContain('const refreshWorkspaceData = () => {');
    expect(source).toContain("queryKey: ['applications']");
    expect(source).toContain("queryKey: ['events']");
    expect(source).toContain("queryKey: ['offers']");
    expect(source).toContain("queryKey: ['questions', 'stats']");
    expect(source).toContain('onDataChanged={refreshWorkspaceData}');
  });

  it('renders Pilot as a normal tab with the expanded assistant workspace', () => {
    expect(source).toContain("view === 'pilot'");
    expect(source).toContain('variant="page"');
    expect(source).not.toContain('PilotHomeView');
  });

  it('keeps the contextual Pilot rail out of the Pilot tab itself', () => {
    expect(source).toContain("view !== 'pilot'");
    expect(source).toContain('shouldShowContextualPilot');
  });

  it('routes the docked Pilot expand action into the normal Pilot tab', () => {
    expect(source).toContain("onExpand={() => navigateToView('pilot')}");
    expect(source).not.toContain('onExpand={() => setPilotDrawerOpen(true)}');
  });

  it('starts a fresh application-scoped Pilot draft from shared entry surfaces', () => {
    expect(source).toContain('startApplicationChat');
    expect(source).toContain("context_type: 'application'");
    expect(source).toContain('requestKey:');
    expect(source).toContain('onAskPilot={startApplicationChat}');
  });
});
