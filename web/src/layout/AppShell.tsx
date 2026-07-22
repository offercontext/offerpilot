import { Component, lazy, Suspense, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { DndContext, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Layout, Spin, Tabs, message } from 'antd';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { ONBOARDING_QUERY_KEY } from '@/services/onboarding';
import { uploadResume } from '@/services/resumes';
import { listResumes } from '@/services/resumes';
import {
  createOpportunityFitReview,
  createOpportunityFitDeepReview,
  getOpportunityFitReview,
  listOpportunityFitReviews,
} from '@/services/opportunityFitReviews';
import PilotOpportunityFitCard, { type PilotOpportunityFitMaterialHandoff } from '@/features/pilot/PilotOpportunityFitCard';
import {
  createOpportunityFitDraftStore,
  removeOpportunityFitDraftStore,
  shouldRetainOpportunityFitDraft,
  type OpportunityFitDraftAction,
  type OpportunityFitDraftState,
  type OpportunityFitDraftStore,
  type OpportunityFitResumeEvidenceProof,
} from '@/features/pilot/opportunityFitDraft';
import {
  cancelPilotTriage,
  isOpportunityFitNotFoundError,
  restorePilotHistoricalReview,
  runPilotDeepReview,
  runPilotTriage,
} from '@/features/pilot/pilotOpportunityFitLifecycle';
import { discardMaterialKitHandoff, writeMaterialKitHandoff } from '@/features/pilot/materialKitHandoff';
import type { Application } from '@/types/application';
import type { OpportunityFitReview } from '@/types/opportunityFitReview';
import type { ChatStartRequest, PilotContextAttachment } from '@/types/chat';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import AddApplicationForm from '@/components/AddApplicationForm';
import ApplicationDetail from '@/components/ApplicationDetail';
import ResumeUploadModal from '@/components/ResumeUploadModal';
import ChatPanel from '@/components/ChatPanel';
import type { EvidenceTarget } from '@/components/ChatPanel/model';
import AISettingsDrawer from '@/components/AISettingsDrawer';
import CommandPalette from './CommandPalette';
import { moduleTabsForView, type ViewMode } from './navigation';
import {
  derivePipelineInsights,
  toLegacyActionItems,
  type PipelineInsight,
} from '@/lib/pipelineInsights';
import { getPracticeStats } from '@/services/questions';
import { buildPilotPageContext } from '@/lib/pilotPageContext';
import { PilotAttachmentProvider } from '@/features/pilot/PilotAttachmentContext';
import {
  usePilotAttachmentStore,
  type PilotAttachmentConversationKey,
} from '@/features/pilot/PilotAttachmentContext';
import { retainPilotAttachmentKey } from '@/features/pilot/attachmentHandoff';
import {
  type OnboardingAction,
  onboardingActionIntent,
} from '@/features/onboarding/actionRouting';
import dayjs from 'dayjs';

const { Content } = Layout;

const KanbanBoard = lazy(() => import('@/components/KanbanBoard'));
const ApplicationListView = lazy(() => import('@/components/ApplicationListView'));
const CalendarView = lazy(() => import('@/components/CalendarView'));
const KnowledgeSourcesView = lazy(() => import('@/components/KnowledgeSourcesView'));
const QuestionBankView = lazy(() => import('@/components/QuestionBankView'));
const OfferCenterView = lazy(() => import('@/components/OfferCenterView'));
const DashboardView = lazy(() => import('@/features/dashboard/DashboardView'));
const RemindersView = lazy(() => import('@/features/reminders/RemindersView'));
const InterviewV01View = lazy(() => import('@/components/InterviewV01View'));
const ResumeLibraryView = lazy(() => import('@/components/ResumeLibraryView'));
const SettingsView = lazy(() => import('@/components/SettingsView'));

const EMPTY_PILOT_DRAFT_STORE = createOpportunityFitDraftStore(0, 'empty');

class ViewErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ textAlign: 'center', padding: 48, color: 'var(--op-muted)' }}>
          <div style={{ marginBottom: 16 }}>View failed to load.</div>
          <Button onClick={() => window.location.reload()}>Reload</Button>
        </div>
      );
    }

    return this.props.children;
  }
}

function computeStreak(apps: Application[], now = dayjs()): number {
  const days = new Set(
    apps.filter((a) => a.applied_at).map((a) => dayjs(a.applied_at).format('YYYY-MM-DD'))
  );
  let streak = 0;
  let cursor = now;
  while (days.has(cursor.format('YYYY-MM-DD'))) {
    streak++;
    cursor = cursor.subtract(1, 'day');
  }
  return streak;
}

export default function AppShell() {
  return (
    <PilotAttachmentProvider>
      <AppShellContent />
    </PilotAttachmentProvider>
  );
}

function AppShellContent() {
  const [view, setView] = useState<ViewMode>('dashboard');
  const [addOpen, setAddOpen] = useState(false);
  const [resumeUploadOpen, setResumeUploadOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [pilotDrawerOpen, setPilotDrawerOpen] = useState(false);
  const [pilotApplicationContext, setPilotApplicationContext] = useState<{ applicationId: number; pilotDraftKey: string } | null>(null);
  const [pilotHistoricalReviewId, setPilotHistoricalReviewId] = useState<number | null>(null);
  const [pilotInterviewReviewApplicationId, setPilotInterviewReviewApplicationId] = useState<number | null>(null);
  const pilotApplicationContextRef = useRef(pilotApplicationContext);
  pilotApplicationContextRef.current = pilotApplicationContext;
  const [aiSettingsOpen, setAISettingsOpen] = useState(false);
  const [resumeOnboardingFocusToken, setResumeOnboardingFocusToken] = useState(0);
  const [pilotOnboardingFocusToken, setPilotOnboardingFocusToken] = useState(0);
  const nextPilotOnboardingFocusToken = useRef(0);
  const [selected, setSelected] = useState<Application | null>(null);
  const [evidenceFocus, setEvidenceFocus] = useState<Exclude<EvidenceTarget, { kind: 'application' }> | null>(null);
  const [coachOfferId, setCoachOfferId] = useState<number | undefined>(undefined);
  const [chatStartRequest, setChatStartRequest] = useState<ChatStartRequest>();
  const [activePilotAttachmentKey, setActivePilotAttachmentKey] = useState<PilotAttachmentConversationKey>();
  const [pendingAttachmentDraftKey, setPendingAttachmentDraftKey] = useState<PilotAttachmentConversationKey>();
  const pilotAttachmentDraftKey = pendingAttachmentDraftKey;
  const pendingAttachmentDraftKeyRef = useRef<PilotAttachmentConversationKey>();
  const nextChatStartRequestKey = useRef(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [now, setNow] = useState(() => dayjs());
  const [pilotRailAvailable, setPilotRailAvailable] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia('(min-width: 1180px)').matches
  );
  const pilotDraftStoresRef = useRef(new Map<string, OpportunityFitDraftStore>());
  const pilotDraftInFlightRef = useRef(new Map<string, number>());
  const pilotDraftCleanupPendingRef = useRef(new Set<string>());
  const pilotDraftKey = (context: { applicationId: number; pilotDraftKey: string }) =>
    `${context.applicationId}:${context.pilotDraftKey}`;
  const findRetainedPilotDraftKey = (applicationId: number): string | null => {
    const prefix = `${applicationId}:`;
    for (const [key, store] of pilotDraftStoresRef.current) {
      if (key.startsWith(prefix) && shouldRetainOpportunityFitDraft(store.getState())) {
        return store.getState().pilotDraftKey;
      }
    }
    return null;
  };
  const schedulePilotDraftCleanup = (context: { applicationId: number; pilotDraftKey: string }) => {
    const key = pilotDraftKey(context);
    const store = pilotDraftStoresRef.current.get(key);
    if (!store) return;
    if (shouldRetainOpportunityFitDraft(store.getState())) return;
    if ((pilotDraftInFlightRef.current.get(key) ?? 0) > 0) {
      pilotDraftCleanupPendingRef.current.add(key);
      return;
    }
    removeOpportunityFitDraftStore(pilotDraftStoresRef.current, key);
  };
  const beginPilotDraftRequest = (context: { applicationId: number; pilotDraftKey: string }) => {
    const key = pilotDraftKey(context);
    pilotDraftInFlightRef.current.set(key, (pilotDraftInFlightRef.current.get(key) ?? 0) + 1);
    pilotDraftCleanupPendingRef.current.delete(key);
  };
  const finishPilotDraftRequest = (context: { applicationId: number; pilotDraftKey: string }) => {
    const key = pilotDraftKey(context);
    const remaining = (pilotDraftInFlightRef.current.get(key) ?? 1) - 1;
    if (remaining > 0) {
      pilotDraftInFlightRef.current.set(key, remaining);
      return;
    }
    pilotDraftInFlightRef.current.delete(key);
    if (pilotDraftCleanupPendingRef.current.delete(key)) {
      const store = pilotDraftStoresRef.current.get(pilotDraftKey(context));
      if (!store || shouldRetainOpportunityFitDraft(store.getState())) return;
      removeOpportunityFitDraftStore(pilotDraftStoresRef.current, key);
    }
  };
  const exitPilotContext = ({ preserveUnknownAttempt = true }: { preserveUnknownAttempt?: boolean } = {}) => {
    const current = pilotApplicationContextRef.current;
    if (!current) return;
    const store = pilotDraftStoresRef.current.get(pilotDraftKey(current));
    if (store) cancelPilotTriage(store, { preserveAttempt: preserveUnknownAttempt });
    schedulePilotDraftCleanup(current);
    setPilotHistoricalReviewId(null);
    setPilotApplicationContext(null);
  };
  const kanbanSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );
  const { addAttachment: addAttachmentToKey, createNewDraftWithAttachment } = usePilotAttachmentStore();

  const { data: applications = [], isLoading, isError: appsError } = useQuery({
    queryKey: ['applications'],
    queryFn: () => listApplications(),
  });
  const { data: events = [] } = useQuery({
    queryKey: ['events'],
    queryFn: () => listEvents(),
  });
  const { data: offers = [] } = useQuery({
    queryKey: ['offers'],
    queryFn: () => listOffers(),
  });
  const { data: practiceStats } = useQuery({
    queryKey: ['questions', 'stats'],
    queryFn: () => getPracticeStats(),
    retry: false,
  });
  const { data: resumes = [] } = useQuery({
    queryKey: ['resumes'],
    queryFn: listResumes,
    enabled: pilotApplicationContext !== null,
  });

  const pilotDraftStore = useMemo(() => {
    if (!pilotApplicationContext) return EMPTY_PILOT_DRAFT_STORE;
    const key = `${pilotApplicationContext.applicationId}:${pilotApplicationContext.pilotDraftKey}`;
    const existing = pilotDraftStoresRef.current.get(key);
    if (existing) return existing;
    const created = createOpportunityFitDraftStore(
      pilotApplicationContext.applicationId,
      pilotApplicationContext.pilotDraftKey,
    );
    pilotDraftStoresRef.current.set(key, created);
    return created;
  }, [pilotApplicationContext]);
  const pilotDraft = useSyncExternalStore(
    pilotDraftStore.subscribe,
    pilotDraftStore.getState,
    pilotDraftStore.getState,
  );
  const pilotHistoryQuery = useQuery({
    queryKey: ['opportunity-fit-reviews', pilotApplicationContext?.applicationId],
    queryFn: () => listOpportunityFitReviews(pilotApplicationContext!.applicationId),
    enabled: Boolean(pilotApplicationContext),
    retry: false,
  });
  const pilotHistoricalReviewQuery = useQuery({
    queryKey: ['opportunity-fit-review', pilotApplicationContext?.applicationId, pilotHistoricalReviewId],
    queryFn: () => getOpportunityFitReview(pilotApplicationContext!.applicationId, pilotHistoricalReviewId!),
    enabled: Boolean(pilotApplicationContext && pilotHistoricalReviewId !== null),
    retry: false,
  });
  const handlePilotNotFound = () => {
    const current = pilotApplicationContextRef.current;
    if (current) discardMaterialKitHandoff(current.applicationId);
    message.error('当前投递或岗位评估已不存在，请重新打开。');
    exitPilotContext({ preserveUnknownAttempt: false });
    setView('dashboard');
  };

  useEffect(() => {
    if (
      isOpportunityFitNotFoundError(pilotHistoryQuery.error)
      || isOpportunityFitNotFoundError(pilotHistoricalReviewQuery.error)
    ) {
      handlePilotNotFound();
    }
  }, [pilotHistoryQuery.error, pilotHistoricalReviewQuery.error]);

  const [resumeEvidenceProof, setResumeEvidenceProof] = useState<OpportunityFitResumeEvidenceProof | null>(null);

  useEffect(() => {
    if (!pilotHistoricalReviewQuery.data || !pilotApplicationContext || pilotHistoricalReviewId === null) return;
    restorePilotHistoricalReview(pilotDraftStore, pilotHistoricalReviewQuery.data);
  }, [pilotHistoricalReviewQuery.data, pilotApplicationContext, pilotDraftStore, pilotHistoricalReviewId]);

  useEffect(() => {
    let cancelled = false;
    const review = pilotDraft.review;
    const resume = review ? resumes.find((item) => item.id === review.source.resume.id) : undefined;
    if (!review || !resume) {
      setResumeEvidenceProof(null);
      return () => { cancelled = true; };
    }

    const stableJson = (value: unknown): string => {
      if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
      if (value && typeof value === 'object') {
        return `{${Object.keys(value as Record<string, unknown>).sort().map((key) => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`).join(',')}}`;
      }
      return JSON.stringify(value);
    };

    void crypto.subtle.digest('SHA-256', new TextEncoder().encode(stableJson(resume.content_json))).then((digest) => {
      const hash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
      if (!cancelled && hash === review.source.resume.sha256) {
        setResumeEvidenceProof({ resumeId: resume.id, sha256: hash, contentJson: resume.content_json });
      } else if (!cancelled) {
        setResumeEvidenceProof(null);
      }
    }).catch(() => {
      if (!cancelled) setResumeEvidenceProof(null);
    });
    return () => { cancelled = true; };
  }, [pilotDraft.review, resumes]);

  // Backend serializes an empty []T slice as JSON `null` (Go encoding/json).
  // React Query's `= []` default only applies when data is `undefined`, so an
  // explicit null-coalesce is needed to keep downstream iterators safe.
  const apps = applications ?? [];
  const evs = events ?? [];
  const ofrs = offers ?? [];

  const qc = useQueryClient();
  const refreshWorkspaceData = () => {
    void qc.invalidateQueries({ queryKey: ['applications'] });
    void qc.invalidateQueries({ queryKey: ['events'] });
    void qc.invalidateQueries({ queryKey: ['calendar'] });
    void qc.invalidateQueries({ queryKey: ['offers'] });
    void qc.invalidateQueries({ queryKey: ['questions', 'stats'] });
    void qc.invalidateQueries({ queryKey: ['chat', 'conversations'] });
    void qc.invalidateQueries({ queryKey: ONBOARDING_QUERY_KEY });
  };

  const uploadResumeMut = useMutation({
    mutationFn: (f: File) => uploadResume(f),
    onSuccess: (res) => {
      message.success(res.parse_status === 'text-ready' ? '上传成功' : '已上传，文本提取失败，请到简历库校正');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      qc.invalidateQueries({ queryKey: ONBOARDING_QUERY_KEY });
      setResumeUploadOpen(false);
    },
    onError: () => message.error('上传失败'),
  });

  useEffect(() => {
    const id = window.setInterval(() => setNow(dayjs()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1180px)');
    const sync = () => setPilotRailAvailable(media.matches);
    sync();
    media.addEventListener('change', sync);
    return () => media.removeEventListener('change', sync);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const pipelineActions = useMemo(
    () => derivePipelineInsights({ apps, events: evs, offers: ofrs, practiceStats, weeklyTarget: 6, now }),
    [apps, evs, ofrs, practiceStats, now]
  );
  const actions = useMemo(() => toLegacyActionItems(pipelineActions), [pipelineActions]);
  const streak = useMemo(() => computeStreak(apps, now), [apps, now]);

  const selectedApp = selected
    ? apps.find((a) => a.id === selected.id) ?? null
    : null;
  const coachedOffer = ofrs.find((offer) => offer.id === coachOfferId);
  const pageContext = useMemo(
    () =>
      buildPilotPageContext({
        view,
        selectedApplication: selectedApp ?? undefined,
        coachedOffer,
      }),
    [view, selectedApp, coachedOffer]
  );
  const moduleTabs = moduleTabsForView(view);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0 });
  }, [selectedApp?.id, view]);

  useEffect(() => {
    if (selected && !apps.some((app) => app.id === selected.id)) {
      setSelected(null);
    }
  }, [apps, selected]);

  const shouldShowContextualPilot = view !== 'pilot';
  const contextualPilotPanelOpen = pilotRailAvailable ? pilotDrawerOpen : chatOpen;

  const openChat = (offerId?: number) => {
    setCoachOfferId(offerId);
    if (view === 'pilot') {
      setView('dashboard');
    }
    if (pilotRailAvailable) {
      setPilotDrawerOpen(true);
      return;
    }
    setChatOpen(true);
  };

  const attachToPilot = (attachment: PilotContextAttachment) => {
    const attachmentKey =
      activePilotAttachmentKey ?? pendingAttachmentDraftKeyRef.current ?? pendingAttachmentDraftKey;
    if (attachmentKey) {
      pendingAttachmentDraftKeyRef.current = attachmentKey;
      setPendingAttachmentDraftKey(attachmentKey);
      addAttachmentToKey(attachmentKey, attachment);
      return;
    }
    const key = createNewDraftWithAttachment(attachment);
    pendingAttachmentDraftKeyRef.current = key;
    setPendingAttachmentDraftKey(key);
  };

  const syncPilotAttachmentKey = (key?: PilotAttachmentConversationKey) => {
    setActivePilotAttachmentKey((currentKey) => retainPilotAttachmentKey(currentKey, key));
    if (key) {
      pendingAttachmentDraftKeyRef.current = undefined;
      setPendingAttachmentDraftKey(undefined);
    }
  };

  const handoffPilotAttachmentDraft = () => {
    const attachmentKey =
      activePilotAttachmentKey ?? pendingAttachmentDraftKeyRef.current ?? pendingAttachmentDraftKey;
    if (!attachmentKey) return;
    pendingAttachmentDraftKeyRef.current = attachmentKey;
    setPendingAttachmentDraftKey(attachmentKey);
  };

  const startApplicationChat = (application: Application) => {
    setCoachOfferId(undefined);
    setChatStartRequest({
      requestKey: ++nextChatStartRequestKey.current,
      context_type: 'application',
      context_ref: String(application.id),
      context_label: `${application.company_name} · ${application.position_name}`,
      mode: 'general',
    });
    if (view !== 'pilot') {
      if (pilotRailAvailable) setPilotDrawerOpen(true);
      else setChatOpen(true);
    }
  };

  const navigateToView = (nextView: ViewMode, { preserveEvidenceFocus = false }: { preserveEvidenceFocus?: boolean } = {}) => {
    setAISettingsOpen(false);
    setSelected(null);
    if (!preserveEvidenceFocus) setEvidenceFocus(null);
    if (nextView === 'pilot') {
      setChatOpen(false);
      setPilotDrawerOpen(false);
      setCoachOfferId(undefined);
    }
    setView(nextView);
  };

  const consumePilotOnboardingFocus = (token: number) => {
    setPilotOnboardingFocusToken((current) => (current === token ? 0 : current));
  };

  const handleOnboardingAction = (action: OnboardingAction) => {
    const intent = onboardingActionIntent(action, pilotRailAvailable);
    if (intent.view) navigateToView(intent.view);
    if (intent.openAISettings) setAISettingsOpen(true);
    if (intent.openApplicationForm) setAddOpen(true);
    if (intent.focusResumeEntry) setResumeOnboardingFocusToken((token) => token + 1);
    if (intent.openPilotDrawer) setChatOpen(true);
    if (intent.focusPilot) {
      nextPilotOnboardingFocusToken.current += 1;
      setPilotOnboardingFocusToken(nextPilotOnboardingFocusToken.current);
    }
  };

  const openApplicationDetail = (app: Application) => {
    setAISettingsOpen(false);
    exitPilotContext();
    setSelected(app);
  };

  const openPilotInterviewReview = (applicationId: number) => {
    const app = apps.find((item) => item.id === applicationId);
    if (!app) return;
    exitPilotContext();
    setPilotInterviewReviewApplicationId(applicationId);
    setView('board');
    setSelected(app);
  };

  const startPilotOpportunityFit = (app: Application) => {
    setAISettingsOpen(false);
    setSelected(null);
    const currentPilot = pilotApplicationContextRef.current;
    if (currentPilot && currentPilot.applicationId !== app.id) {
      exitPilotContext();
    }
    setPilotHistoricalReviewId(null);
    setPilotApplicationContext((current) => current?.applicationId === app.id
      ? current
      : {
        applicationId: app.id,
        pilotDraftKey: findRetainedPilotDraftKey(app.id) ?? crypto.randomUUID(),
      });
    setView('pilot');
  };

  const dispatchPilotDraft = (action: OpportunityFitDraftAction) => {
    if (pilotApplicationContext) pilotDraftStore.dispatch(action);
  };

  const startPilotTriage = async (draft: OpportunityFitDraftState, existingKey: string | null) => {
    if (!pilotApplicationContext || draft.applicationId !== pilotApplicationContext.applicationId) return;
    const store = pilotDraftStore;
    const applicationContext = pilotApplicationContext;
    beginPilotDraftRequest(applicationContext);
    try {
      await runPilotTriage({
        store,
        applicationId: draft.applicationId,
        pilotDraftKey: applicationContext.pilotDraftKey,
        draft,
        existingKey,
        createReview: createOpportunityFitReview,
        resumeEvidenceProof,
        onNotFound: handlePilotNotFound,
        isContextCurrent: () => {
          const current = pilotApplicationContextRef.current;
          return current?.applicationId === applicationContext.applicationId
            && current.pilotDraftKey === applicationContext.pilotDraftKey
            && pilotDraftStoresRef.current.get(pilotDraftKey(applicationContext)) === store;
        },
      });
    } finally {
      finishPilotDraftRequest(applicationContext);
    }
  };

  const startPilotDeepReview = async (draft: OpportunityFitDraftState, review: OpportunityFitReview) => {
    if (!pilotApplicationContext || draft.applicationId !== pilotApplicationContext.applicationId) return;
    const store = pilotDraftStore;
    const applicationContext = pilotApplicationContext;
    beginPilotDraftRequest(applicationContext);
    try {
      await runPilotDeepReview({
        store,
        applicationId: draft.applicationId,
        pilotDraftKey: applicationContext.pilotDraftKey,
        draft,
        review,
        createReview: createOpportunityFitDeepReview,
        resumeEvidenceProof,
        onNotFound: handlePilotNotFound,
        isContextCurrent: () => {
          const current = pilotApplicationContextRef.current;
          return current?.applicationId === applicationContext.applicationId
            && current.pilotDraftKey === applicationContext.pilotDraftKey
            && pilotDraftStoresRef.current.get(pilotDraftKey(applicationContext)) === store;
        },
      });
    } finally {
      finishPilotDraftRequest(applicationContext);
    }
  };

  const preparePilotMaterials = (handoff: PilotOpportunityFitMaterialHandoff) => {
    writeMaterialKitHandoff(handoff);
    const app = apps.find((item) => item.id === handoff.applicationId);
    exitPilotContext();
    setView('board');
    if (app) setSelected(app);
  };

  const startNewPilotReview = () => {
    setPilotHistoricalReviewId(null);
  };

  const viewPilotHistoricalReview = (reviewId: number) => {
    if (pilotDraftStore.getState().reviewSource === 'historical') {
      pilotDraftStore.dispatch({ type: 'reset_for_new_review' });
    }
    setPilotHistoricalReviewId(reviewId);
  };

  const clearEvidenceFocus = (target: EvidenceTarget) => {
    setEvidenceFocus((current) => (current === target ? null : current));
  };

  const openEvidence = (target: EvidenceTarget) => {
    setAISettingsOpen(false);
    if (view === 'pilot' && !pilotRailAvailable) {
      setChatOpen(true);
    }
    if (target.kind === 'application') {
      setEvidenceFocus(null);
      const app = apps.find((item) => item.id === target.id);
      if (app) {
        if (view === 'pilot') setView('board');
        openApplicationDetail(app);
      } else {
        message.warning('引用的记录已不存在');
      }
      return;
    }

    setSelected(null);
    setEvidenceFocus(target);
    if (target.kind === 'offer') {
      navigateToView('offers', { preserveEvidenceFocus: true });
      return;
    }
    if (target.kind === 'resume') {
      navigateToView('resumes', { preserveEvidenceFocus: true });
      return;
    }
    navigateToView('calendar', { preserveEvidenceFocus: true });
  };

  const goDetailById = (appId: number) => {
    const app = apps.find((a) => a.id === appId);
    if (app) openApplicationDetail(app);
  };

  const runPipelineAction = (item: PipelineInsight) => {
    if (item.primaryAction.target === 'board' && item.appId) {
      goDetailById(item.appId);
      return;
    }

    navigateToView(item.primaryAction.target);
  };

  const calendarEvidenceFocus = evidenceFocus?.kind === 'event' ? evidenceFocus : undefined;
  const offerEvidenceFocus = evidenceFocus?.kind === 'offer' ? evidenceFocus : undefined;
  const resumeEvidenceFocus = evidenceFocus?.kind === 'resume' ? evidenceFocus : undefined;

  const workspaceContent = aiSettingsOpen ? (
    <AISettingsDrawer open onClose={() => setAISettingsOpen(false)} />
  ) : selectedApp ? (
    <ApplicationDetail
      application={selectedApp}
      open
      onClose={() => setSelected(null)}
      onAskPilot={startApplicationChat}
      onOpenPilotOpportunityFit={startPilotOpportunityFit}
      pilotInterviewReviewApplicationId={pilotInterviewReviewApplicationId}
      onPilotInterviewReviewFocusConsumed={() => setPilotInterviewReviewApplicationId(null)}
      onAttachToPilot={attachToPilot}
    />
  ) : (
    <>
      {moduleTabs.length > 1 && (
        <Tabs
          className="op-module-tabs"
          activeKey={view}
          onChange={(key) => navigateToView(key as ViewMode)}
          items={moduleTabs.map((item) => ({ key: item.view, label: item.label }))}
        />
      )}
      <Suspense
        fallback={
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin size="large" />
          </div>
        }
      >
        <div className="op-view-enter">
          {view === 'dashboard' && (
            <DashboardView
              onNavigate={navigateToView}
              onOpenDetailById={goDetailById}
              onAddApplication={() => setAddOpen(true)}
              onOnboardingAction={handleOnboardingAction}
            />
          )}
          {view === 'board' && (
            <KanbanBoard applications={apps} onOpenDetail={openApplicationDetail} onAttachToPilot={attachToPilot} />
          )}
          {view === 'applications-list' && (
            <ApplicationListView
              applications={apps}
               events={evs}
               onOpenDetail={openApplicationDetail}
               onAskPilot={startApplicationChat}
               onAttachToPilot={attachToPilot}
            />
          )}
          {view === 'calendar' && (
            <CalendarView
              applications={apps}
              onOpenDetail={openApplicationDetail}
              focusEvent={calendarEvidenceFocus}
              onEvidenceFocusConsumed={calendarEvidenceFocus ? () => clearEvidenceFocus(calendarEvidenceFocus) : undefined}
            />
          )}
          {view === 'reminders' && (
            <RemindersView onNavigate={navigateToView} onOpenDetailById={goDetailById} />
          )}
          {view === 'offers' && (
            <OfferCenterView
              applications={apps}
              onCoach={(offer) => openChat(offer.id)}
              onAttachToPilot={attachToPilot}
              focusOfferId={offerEvidenceFocus?.id}
              onEvidenceFocusConsumed={offerEvidenceFocus ? () => clearEvidenceFocus(offerEvidenceFocus) : undefined}
            />
          )}
          {view === 'knowledge' && <KnowledgeSourcesView />}
          {view === 'questions' && <QuestionBankView />}
          {view === 'interview' && <InterviewV01View />}
          {view === 'resumes' && (
            <ResumeLibraryView
              onAttachToPilot={attachToPilot}
              focusResumeId={resumeEvidenceFocus?.id}
              onEvidenceFocusConsumed={resumeEvidenceFocus ? () => clearEvidenceFocus(resumeEvidenceFocus) : undefined}
              onboardingFocusToken={resumeOnboardingFocusToken}
            />
          )}
          {view === 'pilot' && (
            <div style={{ display: 'grid', gridTemplateColumns: pilotApplicationContext ? 'minmax(0, 1fr) minmax(320px, 0.7fr)' : '1fr', gap: 16, minHeight: 640 }}>
              {pilotApplicationContext ? (
                <PilotOpportunityFitCard
                  draft={pilotDraft}
                  dispatch={dispatchPilotDraft}
                  resumes={resumes}
                  resumeEvidenceProof={resumeEvidenceProof}
                   historicalReview={pilotDraft.reviewSource === 'historical'}
                   historicalReviews={pilotHistoryQuery.data ?? []}
                   onViewHistoricalReview={viewPilotHistoricalReview}
                   onStartNewReview={startNewPilotReview}
                   isHistoryLoading={pilotHistoryQuery.isLoading || pilotHistoricalReviewQuery.isLoading || pilotHistoricalReviewQuery.isFetching}
                  onStartTriage={startPilotTriage}
                  onRetryTriage={startPilotTriage}
                  onStartDeepReview={startPilotDeepReview}
                  onPrepareMaterials={preparePilotMaterials}
                  onOpenInterviewReview={openPilotInterviewReview}
                  isTriageLoading={pilotDraft.phase === 'triage_loading'}
                  isDeepReviewLoading={pilotDraft.phase === 'deep_review_loading'}
                  onCancel={() => {
                    exitPilotContext();
                    setView('dashboard');
                  }}
                />
              ) : null}
              <ChatPanel
                variant="page"
                open
                onboardingFocusToken={pilotOnboardingFocusToken}
                onOnboardingFocusConsumed={consumePilotOnboardingFocus}
                onClose={() => undefined}
                onOpenSettings={() => setAISettingsOpen(true)}
                startRequest={chatStartRequest}
                onDataChanged={refreshWorkspaceData}
                attachmentDraftKey={pilotAttachmentDraftKey}
                onAttachmentKeyChange={syncPilotAttachmentKey}
                onOpenEvidence={openEvidence}
              />
            </div>
          )}
          {view === 'settings' && <SettingsView onOpenAISettings={() => setAISettingsOpen(true)} />}
        </div>
      </Suspense>
    </>
  );

  return (
    <DndContext sensors={kanbanSensors}>
      <Layout
      className="op-app-shell"
      style={{ minHeight: '100vh', background: 'var(--op-layout-bg)' }}
      hasSider
    >
      <Sidebar
        view={view}
        onChange={navigateToView}
        reminderCount={actions.length}
      />
      <Layout className="op-app-main" style={{ background: 'var(--op-layout-bg)', minWidth: 0, width: '100%' }}>
        <TopBar
          streakDays={streak}
          onAdd={() => setAddOpen(true)}
          onSearch={() => setPaletteOpen(true)}
          onOpenSettings={() => setAISettingsOpen(true)}
        />
        <Content className="op-app-content" style={{ padding: '0 24px 24px' }}>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Spin size="large" />
            </div>
          ) : appsError ? (
            <div style={{ textAlign: 'center', padding: 48, color: 'var(--op-muted)' }}>
              加载失败，请稍后重试
            </div>
          ) : (
            <ViewErrorBoundary key={aiSettingsOpen ? 'ai-settings' : selectedApp ? `application-${selectedApp.id}` : view}>
              {workspaceContent}
            </ViewErrorBoundary>
          )}
        </Content>
      </Layout>
      {shouldShowContextualPilot && pilotRailAvailable && !pilotDrawerOpen && (
        <aside className="op-pilot-rail" aria-label="Pilot">
          <ChatPanel
            variant="rail"
            open
            onboardingFocusToken={pilotOnboardingFocusToken}
            onOnboardingFocusConsumed={consumePilotOnboardingFocus}
            pilotDropTarget
            onClose={() => setCoachOfferId(undefined)}
            offerId={coachOfferId}
            onOpenSettings={() => setAISettingsOpen(true)}
            onExpand={() => {
              handoffPilotAttachmentDraft();
              navigateToView('pilot');
            }}
            startRequest={chatStartRequest}
            onDataChanged={refreshWorkspaceData}
            pageContext={pageContext}
            attachmentDraftKey={pilotAttachmentDraftKey}
            onAttachmentKeyChange={syncPilotAttachmentKey}
            onOpenEvidence={openEvidence}
          />
        </aside>
      )}

      <AddApplicationForm open={addOpen} onClose={() => setAddOpen(false)} />
      <ResumeUploadModal
        open={resumeUploadOpen}
        uploading={uploadResumeMut.isPending}
        onSubmit={(f) => uploadResumeMut.mutate(f)}
        onClose={() => setResumeUploadOpen(false)}
      />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        applications={apps}
        onNavigate={navigateToView}
        onOpenDetail={openApplicationDetail}
        onAddApplication={() => setAddOpen(true)}
        onOpenResume={() => navigateToView('resumes')}
        onUploadResume={() => setResumeUploadOpen(true)}
        onOpenChat={() => openChat(undefined)}
        onOpenSettings={() => setAISettingsOpen(true)}
        pipelineActions={pipelineActions}
        onRunPipelineAction={runPipelineAction}
      />
      {shouldShowContextualPilot && contextualPilotPanelOpen && (
        <ChatPanel
          open={contextualPilotPanelOpen}
          onboardingFocusToken={pilotOnboardingFocusToken}
          onOnboardingFocusConsumed={consumePilotOnboardingFocus}
          pilotDropTarget
          onClose={() => {
            setChatOpen(false);
            setPilotDrawerOpen(false);
            setCoachOfferId(undefined);
          }}
          offerId={coachOfferId}
          onOpenSettings={() => setAISettingsOpen(true)}
          startRequest={chatStartRequest}
          onDataChanged={refreshWorkspaceData}
          pageContext={pageContext}
          attachmentDraftKey={pilotAttachmentDraftKey}
          onAttachmentKeyChange={syncPilotAttachmentKey}
          onOpenEvidence={openEvidence}
        />
      )}
      </Layout>
    </DndContext>
  );
}
