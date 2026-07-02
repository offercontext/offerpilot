import { useEffect, useRef, useState, createElement } from 'react';
import { Drawer, App as AntApp } from 'antd';
import { CloseOutlined, RobotOutlined, AppstoreOutlined } from '@ant-design/icons';
import {
  sendChat,
  confirmAction,
  getSettings,
  updateAutoApprove,
  listConversations,
  getConversation,
  deleteConversation,
} from '@/services/chat';
import { getOffer } from '@/services/offers';
import type { ChatResponse, Conversation, PendingAction } from '@/types/chat';
import type { Offer } from '@/types/offer';
import { buildTurns, type UITurn } from './model';
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
}

export default function ChatPanel({ open, onClose, offerId }: Props) {
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
  const endRef = useRef<HTMLDivElement>(null);
  const threadOfferId = useRef<number | undefined>(undefined);

  const activeConv = conversations.find((c) => c.id === convID);
  const isNego = activeConv ? activeConv.mode === 'nego_coach' : offerId !== undefined;
  const capabilities = capabilitiesForMode(isNego);

  function refreshConversations() {
    listConversations()
      .then(setConversations)
      .catch(() => undefined);
  }

  useEffect(() => {
    if (!open) return;
    // Start a fresh thread when the panel opens bound to a different offer
    // context, so coach(offer) and general threads never bleed together.
    if (offerId !== threadOfferId.current) {
      setConvID(undefined);
      setTurns([]);
      setPending(null);
      setDegraded(false);
      threadOfferId.current = offerId;
    }
    getSettings()
      .then((s) => {
        setAutoApprove(s.chat_auto_approve_writes);
        setHasKey(s.has_api_key);
      })
      .catch(() => undefined);
    refreshConversations();
  }, [open, offerId]);

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
      setPending(null);
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

  /** Reload authoritative turns (with tool steps) from the server. */
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
  }

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading || pending) return;
    setTurns((t) => [...t, { role: 'user', content: trimmed }]);
    setLoading(true);
    try {
      const isNew = convID === undefined;
      const resp = await sendChat(trimmed, convID, convID ? undefined : offerId);
      if (resp.type === 'confirmation_required') {
        setConvID(resp.conversation_id);
        setPending(resp.pending_action);
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
        setPending(resp.pending_action);
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
      await updateAutoApprove(value);
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

  const iconBtnStyle: React.CSSProperties = {
    border: '1px solid var(--op-border)',
    background: 'var(--op-surface)',
    color: 'var(--op-muted)',
    borderRadius: 9,
    width: 32,
    height: 32,
    cursor: 'pointer',
    marginLeft: 8,
  };

  return (
    <Drawer
      placement="right"
      width={920}
      style={{ maxWidth: '100vw' }}
      open={open}
      onClose={onClose}
      title={null}
      closable={false}
      styles={{ body: { padding: 16, height: '100%', overflow: 'hidden' } }}
    >
      <div className={styles.workspace}>
        {/* header */}
        <header className={styles.header}>
          <div className={styles.avatar} aria-hidden="true">
            <RobotOutlined />
          </div>
          <div style={{ minWidth: 0 }}>
            <div className={`${styles.headTitle} op-gradient-text`}>OfferPilot 副驾</div>
            <div className={styles.headSub}>基于你的投递 · 日程 · 复盘 · Offer 实时作答</div>
          </div>
          <span className={styles.modeBadge}>{isNego ? '🎯 谈薪教练' : '💡 通用助手'}</span>
          <button
            type="button"
            className={styles.panelToggle}
            aria-label="上下文面板"
            onClick={() => setPanelOpen((v) => !v)}
            style={iconBtnStyle}
          >
            {createElement(AppstoreOutlined)}
          </button>
          <button type="button" aria-label="关闭" onClick={onClose} style={{ ...iconBtnStyle, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
            {createElement(CloseOutlined)}
          </button>
        </header>

        {/* three-pane body */}
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
                    {isNego ? '开始谈薪辅导' : '你好，我是 OfferPilot 副驾'}
                  </div>
                  <div className={styles.emptyHint}>
                    {isNego
                      ? '我会结合这份 offer 和你的复盘，帮你评估、准备话术、模拟谈判。挑一个开始：'
                      : '我能查询并（经你确认后）修改你的投递、日程、复盘与知识库。挑一个常用问题开始：'}
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
                  onConfirm={() => handleConfirm(true)}
                  onCancel={() => handleConfirm(false)}
                />
              )}
              {loading && !pending && <ThinkingIndicator />}
              <div ref={endRef} />
            </div>

            <Composer capabilities={capabilities} disabled={composerDisabled} onSend={sendMessage} />
          </section>

          <ContextPanel
            floating={panelOpen}
            isNego={isNego}
            offer={offer}
            capabilities={capabilities}
            autoApprove={autoApprove}
            hasKey={hasKey}
            degraded={degraded}
            disabled={composerDisabled}
            onCapability={handleCapability}
            onToggleAutoApprove={toggleAutoApprove}
          />
        </div>
      </div>
    </Drawer>
  );
}
