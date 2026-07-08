import { useEffect, useRef, useState, createElement } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Drawer, App as AntApp } from 'antd';
import { CloseOutlined, RobotOutlined, AppstoreOutlined, PlusOutlined, ExpandAltOutlined } from '@ant-design/icons';
import {
  sendChat,
  confirmAction,
  getSettings,
  SETTINGS_QUERY_KEY,
  updateAutoApprove,
  listConversations,
  getConversation,
  deleteConversation,
} from '@/services/chat';
import { getOffer } from '@/services/offers';
import type { ChatResponse, Conversation, PendingAction } from '@/types/chat';
import type { Offer } from '@/types/offer';
import {
  buildTurns,
  collectEvidence,
  pendingActionForConversation,
  reloadConversationTurns,
  type EvidenceItem,
  type UITurn,
} from './model';
import { capabilitiesForMode, type Capability } from './capabilities';
import ThreadRail from './ThreadRail';
import MessageBubble from './MessageBubble';
import ProposalCard from './ProposalCard';
import ThinkingIndicator from './ThinkingIndicator';
import Composer from './Composer';
import ContextPanel from './ContextPanel';
import styles from './ChatPanel.module.css';

interface Props {
  open: boolean;
  onClose: () => void;
  offerId?: number;
  onOpenSettings?: () => void;
  variant?: 'drawer' | 'rail';
  onExpand?: () => void;
}

const CHAT_WIDTH_STORAGE_KEY = 'offerpilot.chatPanelWidth';
const DEFAULT_CHAT_WIDTH = 920;
const MIN_CHAT_WIDTH = 720;

function maxChatWidth() {
  return Math.max(MIN_CHAT_WIDTH, Math.min(window.innerWidth - 32, 1440));
}

function clampChatWidth(width: number) {
  return Math.max(MIN_CHAT_WIDTH, Math.min(width, maxChatWidth()));
}

function textArg(args: Record<string, unknown> | undefined, key: string): string | null {
  const value = args?.[key];
  return typeof value === 'string' && value.trim() ? value.trim().toLowerCase() : null;
}

function evidenceMatchesPendingAction(item: EvidenceItem, action: PendingAction): boolean {
  const id = action.args?.id;
  if (typeof id === 'number' || typeof id === 'string') {
    const needle = String(id);
    return item.id === needle || item.id.endsWith(`-${needle}`);
  }

  const company = textArg(action.args, 'company_name');
  const position = textArg(action.args, 'position_name');
  const title = textArg(action.args, 'title');
  const itemTitle = item.title.toLowerCase();
  const itemMeta = item.meta?.toLowerCase() ?? '';

  if (company && position) return itemTitle === company && itemMeta.includes(position);
  if (company) return itemTitle === company;
  if (title) return itemTitle === title;
  return false;
}

function pendingActionEvidence(evidence: EvidenceItem[], action: PendingAction): EvidenceItem[] {
  return evidence.filter((item) => evidenceMatchesPendingAction(item, action));
}

export default function ChatPanel({ open, onClose, offerId, onOpenSettings, variant = 'drawer', onExpand }: Props) {
  const { message: toast } = AntApp.useApp();
  const [turns, setTurns] = useState<UITurn[]>([]);
  const [convID, setConvID] = useState<number | undefined>(undefined);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [loading, setLoading] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
  const [hasKey, setHasKey] = useState(true);
  const [degraded, setDegraded] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [offer, setOffer] = useState<Offer | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [drawerWidth, setDrawerWidth] = useState(() => {
    const stored = Number(localStorage.getItem(CHAT_WIDTH_STORAGE_KEY));
    return Number.isFinite(stored) && stored > 0 ? clampChatWidth(stored) : DEFAULT_CHAT_WIDTH;
  });
  const endRef = useRef<HTMLDivElement>(null);
  const threadOfferId = useRef<number | undefined>(undefined);
  const docked = variant === 'rail';

  const activeConv = conversations.find((c) => c.id === convID);
  const isNego = activeConv ? activeConv.mode === 'nego_coach' : offerId !== undefined;
  const capabilities = capabilitiesForMode(isNego);
  const settingsQuery = useQuery({
    queryKey: SETTINGS_QUERY_KEY,
    queryFn: getSettings,
    enabled: open,
  });

  function refreshConversations() {
    listConversations()
      .then(setConversations)
      .catch(() => undefined);
  }

  useEffect(() => {
    if (!open) return;
    if (offerId !== threadOfferId.current) {
      setConvID(undefined);
      setTurns([]);
      setPending(null);
      setDegraded(false);
      threadOfferId.current = offerId;
    }
    refreshConversations();
  }, [open, offerId]);

  useEffect(() => {
    if (!settingsQuery.data) return;
    setAutoApprove(settingsQuery.data.chat_auto_approve_writes);
    setHasKey(settingsQuery.data.has_api_key);
  }, [settingsQuery.data]);

  useEffect(() => {
    if (offerId === undefined) {
      setOffer(null);
      return;
    }
    getOffer(offerId)
      .then(setOffer)
      .catch(() => setOffer(null));
  }, [offerId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, pending, loading]);

  useEffect(() => {
    const onResize = () => setDrawerWidth((w) => clampChatWidth(w));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    localStorage.setItem(CHAT_WIDTH_STORAGE_KEY, String(drawerWidth));
  }, [drawerWidth]);

  function startResize(e: React.PointerEvent<HTMLDivElement>) {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = drawerWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMove = (move: PointerEvent) => {
      setDrawerWidth(clampChatWidth(startWidth + startX - move.clientX));
    };
    const onUp = () => {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  function startNewChat() {
    setConvID(undefined);
    setTurns([]);
    setPending(null);
    setDegraded(false);
    setPanelOpen(false);
  }

  async function selectConversation(id: number) {
    if (id === convID) return;
    setLoading(true);
    try {
      const stored = await getConversation(id);
      setConvID(id);
      setTurns(buildTurns(stored));
      setPending(pendingActionForConversation(conversations, id));
      setDegraded(false);
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '加载对话失败');
    } finally {
      setLoading(false);
    }
  }

  async function removeConversation(id: number) {
    try {
      await deleteConversation(id);
      if (id === convID) startNewChat();
      refreshConversations();
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '删除失败');
    }
  }

  async function finishMessage(resp: Extract<ChatResponse, { type: 'message' }>) {
    setConvID(resp.conversation_id);
    setPending(null);
    setDegraded(!!resp.degraded);
    try {
      const stored = await getConversation(resp.conversation_id);
      setTurns(buildTurns(stored));
    } catch {
      setTurns((t) => [...t, { role: 'assistant', content: resp.message }]);
    }
    refreshConversations();
  }

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading || pending) return;
    setTurns((t) => [...t, { role: 'user', content: trimmed }]);
    setLoading(true);
    try {
      const isNew = convID === undefined;
      const context =
        isNew && offer?.application_id
          ? { context_type: 'application', context_ref: offer.application_id, mode: 'nego_coach' }
          : isNew && offerId !== undefined
            ? { context_type: 'workspace', context_ref: '', mode: 'nego_coach' }
            : undefined;
      const resp = await sendChat(trimmed, convID, context);
      if (resp.type === 'confirmation_required') {
        setConvID(resp.conversation_id);
        const storedTurns = await reloadConversationTurns(resp.conversation_id, getConversation);
        if (storedTurns) setTurns(storedTurns);
        setPending(resp.pending_action);
        refreshConversations();
      } else {
        await finishMessage(resp);
        if (resp.degraded) toast.info('当前模型不支持工具调用，已切换为只读摘要模式');
      }
      if (isNew) refreshConversations();
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '对话失败');
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm(approved: boolean) {
    if (!convID) return;
    setLoading(true);
    try {
      const resp = await confirmAction(convID, approved);
      if (resp.type === 'confirmation_required') {
        setConvID(resp.conversation_id);
        const storedTurns = await reloadConversationTurns(resp.conversation_id, getConversation);
        if (storedTurns) setTurns(storedTurns);
        setPending(resp.pending_action);
        refreshConversations();
      } else {
        await finishMessage(resp);
      }
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '确认失败');
    } finally {
      setLoading(false);
    }
  }

  async function toggleAutoApprove(value: boolean) {
    setAutoApprove(value);
    try {
      const settings = await updateAutoApprove(value);
      setAutoApprove(settings.chat_auto_approve_writes);
      setHasKey(settings.has_api_key);
    } catch {
      setAutoApprove(!value);
      toast.error('设置保存失败');
    }
  }

  function handleCapability(cap: Capability) {
    setPanelOpen(false);
    sendMessage(cap.prompt);
  }

  const composerDisabled = loading || !!pending || !hasKey;
  const showEmpty = turns.length === 0 && !pending && !loading;
  const threadEvidence = collectEvidence(turns);
  const confirmationEvidence = pending ? pendingActionEvidence(threadEvidence, pending) : [];

  const iconBtnStyle: React.CSSProperties = {
    border: '1px solid var(--op-border)',
    background: 'var(--op-surface)',
    color: 'var(--op-muted)',
    borderRadius: 8,
    width: 32,
    height: 32,
    cursor: 'pointer',
    marginLeft: 8,
  };

  if (!open) return null;

  const workspace = (
    <>
      {!docked && (
        <div
          className={styles.resizeHandle}
          role="separator"
          aria-orientation="vertical"
          aria-label="调整 Pilot 宽度"
          onPointerDown={startResize}
        />
      )}
      <div className={`${styles.workspace} ${docked ? styles.workspaceDocked : ''}`}>
        <header className={styles.header}>
          <div className={styles.avatar} aria-hidden="true">
            <RobotOutlined />
          </div>
          <div style={{ minWidth: 0 }}>
            <div className={`${styles.headTitle} op-gradient-text`}>OfferPilot 领航员</div>
            <div className={styles.headSub}>基于投递、日程、复盘与 Offer 实时作答</div>
          </div>
          <span className={styles.modeBadge}>{isNego ? '谈薪教练' : '通用助手'}</span>
          {docked && (
            <button
              type="button"
              className={styles.dockedNewChat}
              aria-label="新建对话"
              title="新建对话"
              onClick={startNewChat}
              style={{ ...iconBtnStyle, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
            >
              {createElement(PlusOutlined)}
            </button>
          )}
          {docked && onExpand && (
            <button
              type="button"
              className={styles.dockedExpand}
              aria-label="展开完整助手"
              title="展开完整助手"
              onClick={onExpand}
              style={{ ...iconBtnStyle, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
            >
              {createElement(ExpandAltOutlined)}
            </button>
          )}
          <button
            type="button"
            className={styles.panelToggle}
            aria-label="上下文面板"
            onClick={() => setPanelOpen((v) => !v)}
            style={iconBtnStyle}
          >
            {createElement(AppstoreOutlined)}
          </button>
          {(!docked || offerId !== undefined) && (
            <button
              type="button"
              aria-label={docked ? '退出 Offer 上下文' : '关闭'}
              onClick={onClose}
              style={{ ...iconBtnStyle, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
            >
              {createElement(CloseOutlined)}
            </button>
          )}
        </header>

        <div className={styles.body}>
          <ThreadRail
            conversations={conversations}
            activeId={convID}
            onSelect={selectConversation}
            onNew={startNewChat}
            onDelete={removeConversation}
          />

          <section className={styles.center}>
            <div className={styles.stream}>
              {showEmpty ? (
                <div className={styles.empty}>
                  <div className={styles.emptyTitle}>
                    {isNego ? '开始谈薪辅导' : '你好，我是 OfferPilot 领航员'}
                  </div>
                  <div className={styles.emptyHint}>
                    {isNego
                      ? '我会结合这份 Offer 与你的复盘，帮你评估、准备话术、模拟谈判。'
                      : '我能查询投递、日程、复盘与知识库，并在写入前向你确认。'}
                  </div>
                  <div className={styles.emptyPrompts}>
                    {capabilities.map((cap) => (
                      <button
                        key={cap.id}
                        type="button"
                        className={styles.promptCard}
                        disabled={composerDisabled}
                        onClick={() => handleCapability(cap)}
                      >
                        <span className={styles.promptIcon} aria-hidden="true">
                          {createElement(cap.icon)}
                        </span>
                        {cap.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                turns.map((turn, i) => <MessageBubble key={i} turn={turn} index={i} />)
              )}

              {pending && (
                <ProposalCard
                  action={pending}
                  loading={loading}
                  evidence={confirmationEvidence}
                  onConfirm={() => handleConfirm(true)}
                  onCancel={() => handleConfirm(false)}
                />
              )}
              {loading && !pending && <ThinkingIndicator />}
              <div ref={endRef} />
            </div>

            {!hasKey && (
              <div className={styles.inlineKeyNotice}>
                <span>尚未配置 API key，配置后即可使用 Pilot 对话和工具调用。</span>
                {onOpenSettings && (
                  <button type="button" onClick={onOpenSettings}>
                    打开 AI 设置
                  </button>
                )}
              </div>
            )}
            <Composer capabilities={capabilities} disabled={composerDisabled} onSend={sendMessage} />
          </section>

          <ContextPanel
            floating={panelOpen}
            isNego={isNego}
            offer={offer}
            capabilities={capabilities}
            evidence={threadEvidence}
            autoApprove={autoApprove}
            hasKey={hasKey}
            degraded={degraded}
            disabled={composerDisabled}
            onCapability={handleCapability}
            onToggleAutoApprove={toggleAutoApprove}
            onOpenSettings={onOpenSettings}
          />
        </div>
      </div>
    </>
  );

  if (docked) return workspace;

  return (
    <Drawer
      placement="right"
      width={drawerWidth}
      style={{ maxWidth: '100vw' }}
      open={open}
      onClose={onClose}
      title={null}
      closable={false}
      styles={{ body: { padding: 16, height: '100%', overflow: 'hidden', position: 'relative' } }}
    >
      {workspace}
    </Drawer>
  );
}
