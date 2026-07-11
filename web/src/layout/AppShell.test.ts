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
    expect(source).toContain('handoffPilotAttachmentDraft();');
    expect(source).toContain("navigateToView('pilot');");
    expect(source).not.toContain('onExpand={() => setPilotDrawerOpen(true)}');
  });

  it('starts a fresh application-scoped Pilot draft from shared entry surfaces', () => {
    expect(source).toContain('startApplicationChat');
    expect(source).toContain("context_type: 'application'");
    expect(source).toContain('requestKey:');
    expect(source).toContain('onAskPilot={startApplicationChat}');
  });

  it('derives page context from the active view, application, and coached offer', () => {
    expect(source).toContain('const coachedOffer = ofrs.find((offer) => offer.id === coachOfferId);');
    expect(source).toContain('const pageContext = useMemo(');
    expect(source).toContain('buildPilotPageContext({');
    expect(source).toContain('selectedApplication: selectedApp');
    expect(source).toContain('coachedOffer');
    expect(source).toContain('[view, selectedApp, coachedOffer]');
  });

  it('passes page context only to contextual Pilot panels', () => {
    const fullPilotStart = source.indexOf("{view === 'pilot'");
    const fullPilotEnd = source.indexOf("{view === 'settings'", fullPilotStart);
    const fullPilotSource = source.slice(fullPilotStart, fullPilotEnd);

    expect(fullPilotSource).toContain('variant="page"');
    expect(fullPilotSource).not.toContain('pageContext=');
    expect(source.match(/pageContext=\{pageContext\}/g)).toHaveLength(2);
  });

  it('shares one attachment provider across business surfaces and every Pilot panel', () => {
    expect(source).toContain("import { PilotAttachmentProvider } from '@/features/pilot/PilotAttachmentContext'");
    expect(source).toContain('<PilotAttachmentProvider>');
    expect(source).toContain('</PilotAttachmentProvider>');
    expect(source.indexOf('<PilotAttachmentProvider>')).toBeLessThan(source.indexOf('<Layout'));
  });

  it('keeps card attachments on the selected keyed draft across every Pilot panel', () => {
    const fullPilotStart = source.indexOf("{view === 'pilot'");
    const fullPilotEnd = source.indexOf("{view === 'settings'", fullPilotStart);
    const fullPilotSource = source.slice(fullPilotStart, fullPilotEnd);

    expect(fullPilotSource).toContain('onAttachmentKeyChange={syncPilotAttachmentKey}');
    expect(source).toContain('pendingAttachmentDraftKeyRef.current ?? pendingAttachmentDraftKey');
  });

  it('hands the active rail attachment draft to drawer and Pilot page replacements', () => {
    const fullPilotStart = source.indexOf("{view === 'pilot'");
    const fullPilotEnd = source.indexOf("{view === 'settings'", fullPilotStart);
    const fullPilotSource = source.slice(fullPilotStart, fullPilotEnd);

    expect(source).toContain(
      'const pilotAttachmentDraftKey = pendingAttachmentDraftKey;',
    );
    expect(source).toContain(
      "import { retainPilotAttachmentKey } from '@/features/pilot/attachmentHandoff'",
    );
    expect(source).toContain('setActivePilotAttachmentKey((currentKey) => retainPilotAttachmentKey(currentKey, key));');
    expect(source).toContain('const handoffPilotAttachmentDraft = () => {');
    expect(source).toContain('handoffPilotAttachmentDraft();');
    expect(fullPilotSource).toContain('attachmentDraftKey={pilotAttachmentDraftKey}');
    expect(source.match(/attachmentDraftKey=\{pilotAttachmentDraftKey\}/g)).toHaveLength(3);
  });

  it('registers a dnd-kit Pilot target for both visible Pilot surfaces', () => {
    expect(source).toContain('const contextualPilotPanelOpen = pilotRailAvailable ? pilotDrawerOpen : chatOpen;');
    expect(source).toContain('shouldShowContextualPilot && contextualPilotPanelOpen &&');
    expect(source.match(/pilotDropTarget/g)).toHaveLength(2);
  });

  it('keeps a visible Pilot open state unchanged when a card is attached', () => {
    const attachStart = source.indexOf('const attachToPilot =');
    const attachEnd = source.indexOf('const syncPilotAttachmentKey =', attachStart);
    const attachSource = source.slice(attachStart, attachEnd);

    expect(attachSource).not.toContain('openChat();');
    expect(attachSource).toContain('addAttachmentToKey(attachmentKey, attachment);');
  });
});
