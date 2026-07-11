import { useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { EvidenceTarget, UITurn } from './model';
import ProcessTimeline from './ProcessTimeline';
import styles from './ChatPanel.module.css';

/** Code block with a hover copy button. */
function Pre({ children }: { children?: React.ReactNode }) {
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  return (
    <pre ref={ref}>
      <button
        type="button"
        className={styles.copyBtn}
        aria-label="复制代码"
        onClick={async () => {
          const text = ref.current?.querySelector('code')?.textContent ?? '';
          try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            /* clipboard unavailable */
          }
        }}
      >
        {copied ? '已复制' : '复制'}
      </button>
      {children}
    </pre>
  );
}

interface Props {
  turn: UITurn;
  index: number;
  onOpenEvidence?: (target: EvidenceTarget) => void;
}

export default function MessageBubble({ turn, index, onOpenEvidence }: Props) {
  const isUser = turn.role === 'user';
  const hasContent = turn.content.trim().length > 0;
  return (
    <div
      className={`${styles.msg} ${isUser ? styles.msgUser : ''}`}
      style={{ animationDelay: `${Math.min(index, 6) * 0.04}s` }}
    >
      <div
        className={`${styles.msgAvatar} ${isUser ? styles.msgAvatarUser : styles.msgAvatarAssistant}`}
        aria-hidden="true"
      >
        {isUser ? '我' : '✦'}
      </div>
      <div className={styles.msgCol}>
        {hasContent ? (
          <div className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleAssistant}`}>
            {isUser ? (
              turn.content
            ) : (
              <div className={styles.markdown}>
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ pre: Pre }}>
                  {turn.content}
                </ReactMarkdown>
              </div>
            )}
          </div>
        ) : null}
        {!isUser && turn.steps ? <ProcessTimeline steps={turn.steps} onOpenEvidence={onOpenEvidence} /> : null}
      </div>
    </div>
  );
}
