import { useState, createElement } from 'react';
import { RightOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { ToolStep } from './model';
import { toolMeta } from './capabilities';
import styles from './ChatPanel.module.css';

interface Props {
  steps: ToolStep[];
}

export default function ProcessTimeline({ steps }: Props) {
  const [open, setOpen] = useState(false);
  if (!steps.length) return null;

  return (
    <div className={`${styles.timeline} ${open ? styles.timelineOpen : ''}`}>
      <div
        className={styles.tlHead}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
      >
        <ThunderboltOutlined aria-hidden="true" />
        <span>AI 做了什么 · 共 {steps.length} 步</span>
        <RightOutlined className={styles.tlChev} aria-hidden="true" />
      </div>
      <div className={styles.tlBody}>
        <div className={styles.tlInner}>
          <ul className={styles.tlSteps}>
            {steps.map((s, i) => {
              const meta = toolMeta(s.name);
              return (
                <li key={i} className={`${styles.step} ${meta.kind === 'write' ? styles.stepWrite : styles.stepRead}`}>
                  <span className={styles.stepIcon} aria-hidden="true">
                    {createElement(meta.icon)}
                  </span>
                  <span>
                    <b>{meta.label}</b>
                    {s.detail ? ` · ${s.detail}` : ''}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}
