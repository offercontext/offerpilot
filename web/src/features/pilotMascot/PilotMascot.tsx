import { useEffect, useRef, useState } from 'react';
import { CloseOutlined, MessageOutlined, MinusOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  live2dPilotMascotRuntime,
  type PilotMascotActivity,
  type PilotMascotRuntime,
  type PilotMascotRuntimeController,
} from './live2dRuntime';
import {
  normalizePilotMascotZoom,
  PILOT_MASCOT_MAX_ZOOM,
  PILOT_MASCOT_MIN_ZOOM,
} from './pilotMascotPreference';
import styles from './PilotMascot.module.css';

export type { PilotMascotActivity, PilotMascotRuntime } from './live2dRuntime';

export interface PilotMascotNotification {
  status: 'success' | 'error';
  conversationId?: number;
}

interface Props {
  activity: PilotMascotActivity;
  panelOpen: boolean;
  onHide: () => void;
  onTogglePilot: () => void;
  zoom?: number;
  onZoomChange?: (zoom: number) => void;
  notification?: PilotMascotNotification | null;
  placement?: 'contextual' | 'pilot-page';
  runtime?: PilotMascotRuntime;
}

const ACTIVITY_COPY: Record<PilotMascotActivity, { label: string; detail: string }> = {
  idle: { label: '随时待命', detail: '点击 Haru，和 Pilot 聊聊' },
  thinking: { label: '正在思考', detail: '我正在整理上下文…' },
  success: { label: '处理完成', detail: '结果已准备好，来看看吧' },
  error: { label: '需要确认', detail: '打开 Pilot 查看发生了什么' },
};

function notificationCopy(notification: PilotMascotNotification | null | undefined) {
  if (!notification) return undefined;
  return notification.status === 'success'
    ? { label: '处理完成', detail: 'Pilot 已完成回答，点击查看' }
    : { label: '回答未完成', detail: '打开 Pilot 查看并决定是否重试' };
}

export default function PilotMascot({
  activity,
  panelOpen,
  onHide,
  onTogglePilot,
  zoom = 1,
  onZoomChange = () => undefined,
  notification,
  placement = 'contextual',
  runtime = live2dPilotMascotRuntime,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const hideRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const runtimeControllerRef = useRef<PilotMascotRuntimeController>();
  const latestActivityRef = useRef(activity);
  const latestZoomRef = useRef(zoom);
  const [menuOpen, setMenuOpen] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  latestActivityRef.current = activity;
  latestZoomRef.current = zoom;
  const copy = notificationCopy(notification) ?? ACTIVITY_COPY[activity];
  const normalizedZoom = normalizePilotMascotZoom(zoom);
  const zoomPercent = Math.round(normalizedZoom * 100);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const abortController = new AbortController();
    let disposed = false;
    void runtime.mount(canvas, abortController.signal).then((controller) => {
      if (disposed) {
        controller.dispose();
        return;
      }
      runtimeControllerRef.current = controller;
      controller.setZoom(latestZoomRef.current);
      controller.setActivity(latestActivityRef.current);
    }).catch(() => {
      if (!disposed && !abortController.signal.aborted) setLoadFailed(true);
    });
    return () => {
      disposed = true;
      abortController.abort();
      runtimeControllerRef.current?.dispose();
      runtimeControllerRef.current = undefined;
    };
  }, [runtime]);

  useEffect(() => {
    runtimeControllerRef.current?.setActivity(activity);
  }, [activity]);

  useEffect(() => {
    runtimeControllerRef.current?.setZoom(normalizedZoom);
  }, [normalizedZoom]);

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

  const setZoom = (nextZoom: number) => onZoomChange(normalizePilotMascotZoom(nextZoom));
  const actionLabel = notification
    ? notification.status === 'success' ? '查看 Pilot 已完成回答' : '查看 Pilot 回答错误'
    : placement === 'pilot-page'
      ? '聚焦 Pilot 输入框'
      : panelOpen ? '收起 OfferPilot 领航员' : '打开 OfferPilot 领航员';

  return (
    <aside
      className={`${styles.mascot} ${panelOpen ? styles.compact : ''} ${
        placement === 'pilot-page' ? styles.pilotPage : ''
      }`}
      data-activity={activity}
      data-notification={notification?.status}
      aria-label="Haru Pilot 看板娘"
    >
      {!panelOpen || notification ? (
        <div className={styles.bubble} role="status" aria-live="polite">
          <strong>{copy.label}</strong>
          <span>{copy.detail}</span>
        </div>
      ) : null}
      <button
        type="button"
        className={styles.characterButton}
        ref={triggerRef}
        aria-label={actionLabel}
        aria-expanded={placement === 'pilot-page' ? undefined : panelOpen}
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
          <div className={styles.zoomHeading} aria-hidden="true">
            <span>角色大小</span>
            <strong>{zoomPercent}%</strong>
          </div>
          <div className={styles.zoomControls}>
            <button
              type="button"
              role="menuitem"
              aria-label="缩小角色"
              disabled={normalizedZoom <= PILOT_MASCOT_MIN_ZOOM}
              onClick={() => setZoom(normalizedZoom - 0.1)}
            >
              <MinusOutlined />
            </button>
            <button
              type="button"
              role="menuitem"
              aria-label="恢复默认大小"
              disabled={normalizedZoom === 1}
              onClick={() => setZoom(1)}
            >
              <ReloadOutlined />
            </button>
            <button
              type="button"
              role="menuitem"
              aria-label="放大角色"
              disabled={normalizedZoom >= PILOT_MASCOT_MAX_ZOOM}
              onClick={() => setZoom(normalizedZoom + 0.1)}
            >
              <PlusOutlined />
            </button>
          </div>
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
