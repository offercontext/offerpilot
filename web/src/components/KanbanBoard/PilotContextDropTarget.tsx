import { useDroppable } from '@dnd-kit/core';
import type { ReactNode } from 'react';
import { PILOT_CONTEXT_DROP_ID } from './applicationLifecycle';
import styles from './PilotContextDropTarget.module.css';

interface PilotContextDropTargetProps {
  children: ReactNode;
}

export default function PilotContextDropTarget({ children }: PilotContextDropTargetProps) {
  const { isOver, setNodeRef } = useDroppable({ id: PILOT_CONTEXT_DROP_ID });

  return (
    <div
      ref={setNodeRef}
      className={`${styles.target} ${isOver ? styles.targetOver : ''}`}
      data-testid="pilot-context-drop"
    >
      {children}
      {isOver ? <div className={styles.dropHint}>Drop to add to Pilot context</div> : null}
    </div>
  );
}
