import { describe, expect, it } from 'vitest';
import source from './AppShell.tsx?raw';
import calendarView from '@/components/CalendarView.tsx?raw';
import offerCenterView from '@/components/OfferCenterView.tsx?raw';
import resumeLibraryView from '@/components/ResumeLibraryView.tsx?raw';

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

  it('routes evidence through one-shot destination focus without changing Pilot visibility', () => {
    expect(source).toContain("import type { EvidenceTarget } from '@/components/ChatPanel/model'");
    expect(source).toContain(
      "const [evidenceFocus, setEvidenceFocus] = useState<Exclude<EvidenceTarget, { kind: 'application' }> | null>(null);",
    );
    expect(source).toContain('const clearEvidenceFocus = (target: EvidenceTarget) => {');
    expect(source).toContain('setEvidenceFocus((current) => (current === target ? null : current));');
    expect(source).toContain('const openEvidence = (target: EvidenceTarget) => {');
    expect(source).toContain("if (view === 'pilot' && !pilotRailAvailable) {");
    expect(source).toContain('setChatOpen(true);');
    expect(source).toContain('onOpenEvidence={openEvidence}');
    expect(source.match(/onOpenEvidence=\{openEvidence\}/g)).toHaveLength(3);
  });

  it('passes exact evidence focus targets to their destination views', () => {
    expect(source).toContain("const calendarEvidenceFocus = evidenceFocus?.kind === 'event' ? evidenceFocus : undefined;");
    expect(source).toContain("const offerEvidenceFocus = evidenceFocus?.kind === 'offer' ? evidenceFocus : undefined;");
    expect(source).toContain("const resumeEvidenceFocus = evidenceFocus?.kind === 'resume' ? evidenceFocus : undefined;");
    expect(source).toContain('focusOfferId={offerEvidenceFocus?.id}');
    expect(source).toContain('focusResumeId={resumeEvidenceFocus?.id}');
    expect(source).toContain('focusEvent={calendarEvidenceFocus}');
    expect(source).toContain('onEvidenceFocusConsumed={offerEvidenceFocus ? () => clearEvidenceFocus(offerEvidenceFocus) : undefined}');
    expect(source).toContain('onEvidenceFocusConsumed={resumeEvidenceFocus ? () => clearEvidenceFocus(resumeEvidenceFocus) : undefined}');
    expect(source).toContain('onEvidenceFocusConsumed={calendarEvidenceFocus ? () => clearEvidenceFocus(calendarEvidenceFocus) : undefined}');
  });

  it('closes offer comparison before opening focused evidence in the editor', () => {
    const focusStart = offerCenterView.indexOf('const offer = findEvidenceFocusRecord(offers, focusOfferId);');
    const focusEnd = offerCenterView.indexOf('onEvidenceFocusConsumed?.();', focusStart);
    const focusEffect = offerCenterView.slice(focusStart, focusEnd);

    expect(focusEffect).toContain('setCompareOpen(false);');
    expect(focusEffect.indexOf('setCompareOpen(false);')).toBeLessThan(focusEffect.indexOf('setEditing(offer);'));
    expect(focusEffect.indexOf('setEditing(offer);')).toBeLessThan(focusEffect.indexOf('setAddOpen(true);'));
  });

  it('retains destination focus while its queried data is in an error state', () => {
    expect(offerCenterView).toContain('const { data: offers = [], isLoading, isError, isFetching, refetch } = useQuery({');
    expect(offerCenterView).toContain('if (focusOfferId === undefined || isLoading || isError || isFetching) return;');
    expect(resumeLibraryView).toContain('resumesQuery.isFetching');
    expect(calendarView).toContain('const { data: rawEntries, isLoading, isError, isFetching, refetch } = useQuery({');
    expect(calendarView).toContain('if (focusedEventId === null || !selectedDate || isLoading || isError || isFetching) return;');
  });

  it('keeps missing calendar-event cleanup local after handing off valid focus', () => {
    const initialFocusStart = calendarView.indexOf('const date = eventFocusDate(focusEvent.scheduledAt);');
    const verificationStart = calendarView.indexOf('if (focusedEventId === null', initialFocusStart);
    const verificationEnd = calendarView.indexOf('const deleteMutation', verificationStart);
    const initialFocus = calendarView.slice(initialFocusStart, verificationStart);
    const verification = calendarView.slice(verificationStart, verificationEnd);

    expect(initialFocus).toContain('setFocusedEventId(focusEvent.id);');
    expect(initialFocus).toContain('if (isError || isFetching || consumedEvidenceTarget.current === focusEvent) return;');
    expect(verification).toContain('setFocusedEventId(null);');
    expect(verification).not.toContain('onEvidenceFocusConsumed?.();');
  });

  it('routes onboarding setup actions through their declared intents', () => {
    expect(source).toContain('const handleOnboardingAction = (action: OnboardingAction) => {');
    expect(source).toContain('const intent = onboardingActionIntent(action, pilotRailAvailable);');
    expect(source).toContain('navigateToView(intent.view);');
    expect(source).toContain('setAISettingsOpen(true);');
    expect(source).toContain('setAddOpen(true);');
    expect(source).toContain('setResumeOnboardingFocusToken((token) => token + 1);');
    expect(source).toContain('const nextPilotOnboardingFocusToken = useRef(0);');
    expect(source).toContain('nextPilotOnboardingFocusToken.current += 1;');
    expect(source).toContain('const consumePilotOnboardingFocus = (token: number) => {');
    expect(source).toContain('setPilotOnboardingFocusToken((current) => (current === token ? 0 : current));');
    expect(source).toContain('onOnboardingFocusConsumed={consumePilotOnboardingFocus}');
    expect(source).toContain('onOnboardingAction={handleOnboardingAction}');
  });
});
