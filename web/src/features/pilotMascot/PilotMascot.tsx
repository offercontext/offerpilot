import { useEffect, useRef, useState } from 'react';
import { CloseOutlined, MessageOutlined } from '@ant-design/icons';
import { live2dPilotMascotRuntime, type PilotMascotRuntime } from './live2dRuntime';
import styles from './PilotMascot.module.css';

export type PilotMascotActivity = 'idle' | 'thinking' | 'success' | 'error';
export type { PilotMascotRuntime } from './live2dRuntime';

interface Props {
  activity: PilotMascotActivity;
  panelOpen: boolean;
  onHide: () => void;
  onTogglePilot: () => void;
  runtime?: PilotMascotRuntime;
}

const ACTIVITY_COPY: Record<PilotMascotActivity, { label: string; detail: string }> = {
  idle: { label: '随时待命', detail: '点击 Haru，和 Pilot 聊聊' },
  thinking: { label: '正在思考', detail: '我正在整理上下文…' },
  success: { label: '处理完成', detail: '结果已准备好，来看看吧' },
  error: { label: '需要确认', detail: '打开 Pilot 查看发生了什么' },
};

export default function PilotMascot({
  activity,
  panelOpen,
  onHide,
  onTogglePilot,
  runtime = live2dPilotMascotRuntime,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const hideRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const copy = ACTIVITY_COPY[activity];

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const controller = new AbortController();
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void runtime.mount(canvas, controller.signal).then((dispose) => {
      if (disposed) dispose();
      else cleanup = dispose;
    }).catch(() => {
      if (!disposed && !controller.signal.aborted) setLoadFailed(true);
    });
    return () => {
      disposed = true;
      controller.abort();
      cleanup?.();
    };
  }, [runtime]);

  useEffect(() => {
    if (!menuOpen) return;
    hideRef.current?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMenuOpen(false);
        triggerRef.current?.focus();
      }
    };
    const dismiss = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('keydown', close);
    document.addEventListener('pointerdown', dismiss);
    return () => {
      document.removeEventListener('keydown', close);
      document.removeEventListener('pointerdown', dismiss);
    };
  }, [menuOpen]);

  return (
    <aside
      className={`${styles.mascot} ${panelOpen ? styles.compact : ''}`}
      data-activity={activity}
      aria-label="Haru Pilot 看板娘"
    >
      {!panelOpen ? (
        <div className={styles.bubble} role="status" aria-live="polite">
          <strong>{copy.label}</strong>
          <span>{copy.detail}</span>
        </div>
      ) : null}
      <button
        type="button"
        className={styles.characterButton}
        ref={triggerRef}
        aria-label={panelOpen ? '收起 OfferPilot 领航员' : '打开 OfferPilot 领航员'}
        aria-expanded={panelOpen}
        aria-haspopup="menu"
        aria-controls={menuOpen ? 'pilot-mascot-menu' : undefined}
        onClick={onTogglePilot}
        onKeyDown={(event) => {
          if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
            event.preventDefault();
            setMenuOpen(true);
          }
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          setMenuOpen(true);
        }}
      >
        <span className={styles.glow} aria-hidden="true" />
        <span className={styles.canvasHost} aria-hidden="true">
          <canvas ref={canvasRef} className={styles.canvas} />
          {loadFailed ? (
            <span className={styles.fallback}>
              <MessageOutlined />
              <span>Haru 暂时休息中</span>
            </span>
          ) : null}
        </span>
        <span className={styles.nameplate} aria-hidden="true">
          <span className={styles.statusDot} />
          Haru · Pilot
        </span>
      </button>
      {menuOpen ? (
        <div id="pilot-mascot-menu" className={styles.contextMenu} role="menu" ref={menuRef}>
          <button
            type="button"
            role="menuitem"
            ref={hideRef}
            onClick={() => {
              setMenuOpen(false);
              onHide();
            }}
          >
            <CloseOutlined />
            隐藏角色
          </button>
          <span>可在设置中恢复显示</span>
        </div>
      ) : null}
    </aside>
  );
}
