import { Tag } from 'antd';
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import type { ReactNode } from 'react';
import type { ApplicationReadiness, ApplicationReadinessState } from '@/lib/missionControl';
import styles from '../dashboard.module.css';

interface Props {
  items: ApplicationReadiness[];
  focusApplicationId?: number;
  onFocus: (applicationId: number) => void;
}

const STATE_LABELS: Record<ApplicationReadinessState, string> = {
  ready: '就绪',
  watch: '关注',
  blocked: '阻塞',
};

const STATE_ICONS: Record<ApplicationReadinessState, ReactNode> = {
  ready: <CheckCircleOutlined />,
  watch: <WarningOutlined />,
  blocked: <ExclamationCircleOutlined />,
};

export default function ApplicationReadinessStrip({ items, focusApplicationId, onFocus }: Props) {
  if (items.length === 0) {
    return (
      <section className={styles.readinessStrip} aria-label="投递准备度">
        <div className={styles.readinessEmpty}>暂无活跃投递。添加投递后，这里会显示材料、日程和准备状态。</div>
      </section>
    );
  }

  return (
    <section className={styles.readinessStrip} aria-label="投递准备度">
      <div className={styles.sectionHeaderLine}>
        <div>
          <div className={styles.commandEyebrow}>Readiness</div>
          <h2 className={styles.sectionHeading}>重点投递准备度</h2>
        </div>
      </div>
      <div className={styles.readinessList}>
        {items.slice(0, 6).map((item) => (
          <button
            key={item.applicationId}
            type="button"
            className={`${styles.readinessCard} ${styles[`readiness-${item.readiness}`]} ${
              focusApplicationId === item.applicationId ? styles.readinessActive : ''
            }`}
            onClick={() => onFocus(item.applicationId)}
          >
            <span className={styles.readinessIcon} aria-hidden="true">
              {STATE_ICONS[item.readiness]}
            </span>
            <span className={styles.readinessBody}>
              <span className={styles.readinessTitle}>{item.companyName}</span>
              <span className={styles.readinessPosition}>{item.positionName}</span>
              <span className={styles.readinessEvidence}>{item.evidence[0] ?? '暂无准备风险'}</span>
            </span>
            <span className={styles.readinessTags}>
              <Tag>{STATE_LABELS[item.readiness]}</Tag>
              <Tag>{item.materialStatus}</Tag>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
