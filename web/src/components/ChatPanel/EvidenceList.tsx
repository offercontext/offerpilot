import {
  BookOutlined,
  CalendarOutlined,
  DollarOutlined,
  FileTextOutlined,
  ProfileOutlined,
} from '@ant-design/icons';
import { createElement } from 'react';
import type { EvidenceItem } from './model';
import styles from './ChatPanel.module.css';

interface Props {
  items: EvidenceItem[];
  compact?: boolean;
  clamped?: boolean;
}

const ICONS = {
  application: ProfileOutlined,
  event: CalendarOutlined,
  note: FileTextOutlined,
  knowledge: BookOutlined,
  offer: DollarOutlined,
  resume: FileTextOutlined,
  unknown: FileTextOutlined,
} satisfies Record<EvidenceItem['kind'], typeof FileTextOutlined>;

export default function EvidenceList({ items, compact, clamped }: Props) {
  if (!items.length) return null;
  return (
    <ul
      className={`${styles.evidenceList} ${compact ? styles.evidenceListCompact : ''} ${
        clamped ? styles.evidenceListClamped : ''
      }`}
    >
      {items.map((item, index) => {
        const icon = ICONS[item.kind] ?? ICONS.unknown;
        return (
          <li key={`${item.source}-${item.id}-${index}`} className={styles.evidenceItem}>
            <span className={styles.evidenceIcon} aria-hidden="true">
              {createElement(icon)}
            </span>
            <span className={styles.evidenceMain}>
              <span className={styles.evidenceTitle}>{item.title}</span>
              {item.meta ? <span className={styles.evidenceMeta}>{item.meta}</span> : null}
              {item.snippet ? <span className={styles.evidenceSnippet}>{item.snippet}</span> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
