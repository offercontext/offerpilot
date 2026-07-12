import { useEffect, useRef, useState } from 'react';
import { sendChat, getConversation } from '@/services/chat';
import { capabilitiesForMock } from '@/components/ChatPanel/capabilities';
import { buildTurns, type UITurn } from '@/components/ChatPanel/model';
import MessageBubble from '@/components/ChatPanel/MessageBubble';
import Composer from '@/components/ChatPanel/Composer';
import ThinkingIndicator from '@/components/ChatPanel/ThinkingIndicator';
type ChatResponse = import('@/types/chat').ChatResponse;
import { App as AntApp } from 'antd';
import styles from './MockStudio.module.css';

interface Props {
  conversationId: number;
  questionCount: number;
  questionIndex: number;
  /** Called after each successful send so the parent can advance question_index display. */
  onProgress?: () => void;
  disabled?: boolean;
}

export default function MockChat({
  conversationId,
  questionCount,
  questionIndex,
  onProgress,
  disabled,
}: Props) {
  const { message: toast } = AntApp.useApp();
  const [turns, setTurns] = useState<UITurn[]>([]);
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  // Seed the inline thread from the stored conversation messages on mount.
  useEffect(() => {
    let cancelled = false;
    getConversation(conversationId)
      .then((msgs) => {
        if (!cancelled) setTurns(buildTurns(msgs));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns, loading]);

  function applyResponse(resp: ChatResponse) {
    if (resp.type === 'message') {
      getConversation(conversationId)
        .then((msgs) => setTurns(buildTurns(msgs)))
        .catch(() => undefined);
      onProgress?.();
    } else {
      toast.info(`需要确认的操作：${resp.pending_action.human}`);
    }
  }

  async function onSend(text: string) {
    if (loading || disabled) return;
    setLoading(true);
    try {
      const resp = await sendChat(text, conversationId);
      applyResponse(resp);
    } catch {
      toast.error('网络错误，请重试。');
    } finally {
      setLoading(false);
    }
  }

  const unlimited = questionCount === 0;

  return (
    <div>
      <div className={styles.runningHeader}>
        <div className={styles.runningMeta}>
          <span>
            第{' '}
            <strong style={{ fontVariantNumeric: 'tabular-nums' }}>
              {Math.max(1, questionIndex || 0) + (loading ? 1 : 0)}
            </strong>
            {unlimited ? '' : ` / ${questionCount}`} 题
          </span>
          <span>会话进行中，AI 扮演面试官逐题追问</span>
        </div>
      </div>
      <div className={styles.thread}>
        {turns.length === 0 && !loading && (
          <div className={styles.threadEmpty}>
            面试即将开始，先发一句话打个招呼吧，或直接回答面试官的第一个问题。
          </div>
        )}
        {turns.map((t, i) => (
          <MessageBubble
            key={i}
            turn={t}
            index={i}
            actionsDisabled={loading || !!disabled}
            onAction={() => undefined}
            taskCardsEnabled={false}
          />
        ))}
        {loading && <ThinkingIndicator />}
        <div ref={endRef} />
      </div>
      <div className={styles.composerWrap}>
        <Composer
          capabilities={capabilitiesForMock()}
          disabled={loading || disabled}
          onSend={onSend}
          placeholder="回答面试官，或输入 / 唤起控制命令…"
        />
      </div>
    </div>
  );
}
