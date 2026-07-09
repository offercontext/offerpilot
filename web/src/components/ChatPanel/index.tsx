import { useEffect, useRef, useState, createElement } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Drawer, App as AntApp, Button } from 'antd';
import {
  CloseOutlined,
  RobotOutlined,
  AppstoreOutlined,
  PlusOutlined,
  ExpandAltOutlined,
  StopOutlined,
} from '@ant-design/icons';
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
  firstPendingConversationId,
  pendingActionForConversation,
  pendingComposerDisabledReason,
  reloadConversationTurns,
  resolveActivePendingAction,
  toolMeta,
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
  onDataChanged?: () => void;
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

function isAbortError(error: unknown): boolean {
  const candidate = error as { code?: string; name?: string; message?: string };
  return candidate?.code === 'ERR_CANCELED' || candidate?.name === 'CanceledError' || candidate?.message === 'canceled';
}

export default function ChatPanel({
  open,
  onClose,
  offerId,
  onOpenSettings,
  variant = 'drawer',
  onExpand,
  onDataChanged,
}: Props) {
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
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastFailedText, setLastFailedText] = useState('');
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [loadingLabel, setLoadingLabel] = useState<string | undefined>(undefined);
  const [drawerWidth, setDrawerWidth] = useState(() => {
    const stored = Number(localStorage.getItem(CHAT_WIDTH_STORAGE_KEY));
    return Number.isFinite(stored) && stored > 0 ? clampChatWidth(stored) : DEFAULT_CHAT_WIDTH;
  });
  const endRef = useRef<HTMLDivElement>(null);
  const threadOfferId = useRef<number | undefined>(undefined);
  const abortControllerRef = useRef<AbortController | null>(null);
  const docked = variant === 'rail';

  const activeConv = conversations.find((c) => c.id === convID);
  const isNego = activeConv ? activeConv.mode === 'nego_coach' : offerId !== undefined;
  const capabilities = capabilitiesForMode(isNego);
  const activePending = resolveActivePendingAction(pending, conversations, convID);
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
    stopActiveRequest({ silent: true });
    setConvID(undefined);
    setTurns([]);
    setPending(null);
    setDegraded(false);
    setPanelOpen(false);
    setLastError(null);
    setLastFailedText('');
    setConfirmError(null);
    setLoadingLabel(undefined);
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
      setConfirmError(null);
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

  useEffect(() => {
    if (!open || convID !== undefined || turns.length > 0 || loading) return;
    const pendingConversationId = firstPendingConversationId(conversations);
    if (pendingConversationId === undefined) return;
    void selectConversation(pendingConversationId);
  }, [open, convID, conversations, turns.length, loading]);

  async function finishMessage(resp: Extract<ChatResponse, { type: 'message' }>) {
    setConvID(resp.conversation_id);
    setPending(null);
    setDegraded(!!resp.degraded);
    setConfirmError(null);
    try {
      const stored = await getConversation(resp.conversation_id);
      setTurns(buildTurns(stored));
    } catch {
      setTurns((t) => [...t, { role: 'assistant', content: resp.message }]);
    }
    refreshConversations();
  }

  function stopActiveRequest(options: { silent?: boolean } = {}) {
    const controller = abortControllerRef.current;
    if (!controller) return;
    controller.abort();
    abortControllerRef.current = null;
    setLoading(false);
    if (!options.silent) toast.info('已停止当前回复');
  }

  async function sendMessage(text: string): Promise<boolean> {
    const trimmed = text.trim();
    if (!trimmed || loading || activePending) return false;
    setLastError(null);
    setLastFailedText('');
    setConfirmError(null);
    setLoadingLabel('正在理解你的问题');
    setTurns((t) => [...t, { role: 'user', content: trimmed }]);
    setLoading(true);
    const controller = new AbortController();
    abortControllerRef.current = controller;
    try {
      const isNew = convID === undefined;
      const context =
        isNew && offer?.application_id
          ? { context_type: 'application', context_ref: offer.application_id, mode: 'nego_coach' }
          : isNew && offerId !== undefined
            ? { context_type: 'workspace', context_ref: '', mode: 'nego_coach' }
            : undefined;
      const resp = await sendChat(trimmed, convID, context, { signal: controller.signal });
      if (resp.type === 'confirmation_required') {
        setLoadingLabel('正在准备确认卡片');
        setConvID(resp.conversation_id);
        setPending(resp.pending_action);
        const storedTurns = await reloadConversationTurns(resp.conversation_id, getConversation);
        if (storedTurns) setTurns(storedTurns);
        refreshConversations();
      } else {
        await finishMessage(resp);
        if (autoApprove) onDataChanged?.();
        if (resp.degraded) toast.info('当前模型不支持工具调用，已切换为只读摘要模式');
      }
      if (isNew) refreshConversations();
      return true;
    } catch (e: any) {
      if (isAbortError(e)) {
        setTurns((items) => {
          const last = items[items.length - 1];
          return last?.role === 'user' && last.content === trimmed ? items.slice(0, -1) : items;
        });
        return false;
      }
      const error = e?.response?.data?.error ?? '对话失败，请稍后重试';
      setTurns((items) => {
        const last = items[items.length - 1];
        return last?.role === 'user' && last.content === trimmed ? items.slice(0, -1) : items;
      });
      setLastError(error);
      setLastFailedText(trimmed);
      toast.error(error);
      return false;
    } finally {
      if (abortControllerRef.current === controller) abortControllerRef.current = null;
      setLoading(false);
      setLoadingLabel(undefined);
    }
  }

  function retryLastMessage() {
    if (!lastFailedText || loading || activePending) return;
    void sendMessage(lastFailedText);
  }

  function clearLastFailure() {
    setLastError(null);
  }

  function activePendingLabel(action: PendingAction | null): string {
    if (!action) return '本次写入';
    return action.workflow?.current_label || toolMeta(action.tool_name).label;
  }

  async function handleConfirm(approved: boolean) {
    if (!convID) return;
    setConfirmError(null);
    setLoading(true);
    setLoadingLabel(approved ? `正在执行：${activePendingLabel(activePending)}` : '正在取消本次写入');
    const controller = new AbortController();
    abortControllerRef.current = controller;
    try {
      const resp = await confirmAction(convID, approved, { signal: controller.signal });
      if (resp.type === 'confirmation_required') {
        setConvID(resp.conversation_id);
        setPending(resp.pending_action);
        const storedTurns = await reloadConversationTurns(resp.conversation_id, getConversation);
        if (storedTurns) setTurns(storedTurns);
        refreshConversations();
      } else {
        await finishMessage(resp);
        if (approved) onDataChanged?.();
      }
    } catch (e: any) {
      if (isAbortError(e)) return;
      const error = e?.response?.data?.error ?? '确认失败';
      setConfirmError(error);
      toast.error(error);
    } finally {
      if (abortControllerRef.current === controller) abortControllerRef.current = null;
      setLoading(false);
      setLoadingLabel(undefined);
    }
  }

  function retryConfirmAction() {
    if (!activePending || loading) return;
    void handleConfirm(true);
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
    void sendMessage(cap.prompt);
  }

  const composerDisabled = loading || !!activePending || !hasKey;
  const composerDisabledReason = !hasKey
    ? '先配置 API key 后即可对话'
    : activePending
      ? pendingComposerDisabledReason(activePending)
      : loading
        ? 'AI 正在处理，可点击停止当前回复'
        : undefined;
  const showEmpty = turns.length === 0 && !activePending && !loading;
  const threadEvidence = collectEvidence(turns);
  const confirmationEvidence = activePending ? pendingActionEvidence(threadEvidence, activePending) : [];
  const contextLabel =
    activeConv?.context_type === 'application' && activeConv.context_ref
      ? `投递 #${activeConv.context_ref}`
      : isNego
        ? '谈薪上下文'
        : convID
          ? '工作台'
          : null;

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

              {contextLabel ? (
                <div className={styles.contextBadge}>
                  <span>当前上下文</span>
                  <b>{contextLabel}</b>
                </div>
              ) : null}

              {loading && !activePending && <ThinkingIndicator label={loadingLabel} />}
              <div ref={endRef} />
            </div>

            {activePending && (
              <div className={styles.pendingDock}>
                {loading ? <ThinkingIndicator label={loadingLabel} /> : null}
                {confirmError ? (
                  <div className={styles.confirmRecovery}>
                    <span>{confirmError}</span>
                    <button type="button" onClick={retryConfirmAction} disabled={loading}>
                      重试执行
                    </button>
                    <button type="button" onClick={() => handleConfirm(false)} disabled={loading}>
                      取消本次写入
                    </button>
                  </div>
                ) : null}
                <ProposalCard
                  action={activePending}
                  loading={loading}
                  evidence={confirmationEvidence}
                  onConfirm={() => handleConfirm(true)}
                  onCancel={() => handleConfirm(false)}
                />
              </div>
            )}

            {loading && (
              <div className={styles.stopDock}>
                <Button
                  danger
                  icon={<StopOutlined />}
                  aria-label="停止当前回复"
                  onClick={() => stopActiveRequest()}
                >
                  停止当前回复
                </Button>
              </div>
            )}

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
            {lastError && lastFailedText ? (
              <div className={styles.retryNotice}>
                <span>{lastError}</span>
                <button type="button" onClick={retryLastMessage} disabled={composerDisabled}>
                  重新发送
                </button>
                <button type="button" onClick={clearLastFailure}>
                  改成手动整理
                </button>
              </div>
            ) : null}
            <Composer
              capabilities={capabilities}
              disabled={composerDisabled}
              disabledReason={composerDisabledReason}
              onSend={sendMessage}
            />
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
