import styles from './ChatPanel.module.css';

export default function ThinkingIndicator() {
  return (
    <div className={styles.thinking} role="status" aria-live="polite">
      <span className={styles.dots} aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span>领航员正在思考并查阅你的资料…</span>
    </div>
  );
}
