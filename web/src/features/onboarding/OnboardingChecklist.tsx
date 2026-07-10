import { CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import type { OnboardingStatus } from '@/services/onboarding';
import styles from './OnboardingChecklist.module.css';

interface Props {
  status: OnboardingStatus;
  onCollapse: () => void;
}

const STEPS: Array<{ key: keyof OnboardingStatus['steps']; label: string }> = [
  { key: 'configure_ai', label: '配置 AI' },
  { key: 'create_primary_resume', label: '创建主简历' },
  { key: 'create_first_application', label: '添加第一条投递' },
  { key: 'send_first_pilot_message', label: '向 Pilot 发出第一条消息' },
];

export default function OnboardingChecklist({ status, onCollapse }: Props) {
  return (
    <section className={styles.card} aria-label="新手引导">
      <div className={styles.header}>
        <div>
          <div className={styles.title}>四步开始使用 OfferPilot</div>
          <div className={styles.subtitle}>完成这些步骤，建立你的第一条求职工作流。</div>
        </div>
        <div>
          <div className={styles.progress}>{status.completed_count} / {STEPS.length}</div>
          {status.is_complete && (
            <Button type="link" size="small" onClick={onCollapse}>
              收起
            </Button>
          )}
        </div>
      </div>
      <div className={styles.steps}>
        {STEPS.map((step) => {
          const completed = status.steps[step.key];
          return (
            <div key={step.key} className={`${styles.step} ${completed ? styles.completed : ''}`}>
              <div className={styles.stepIcon} aria-hidden="true">
                {completed ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
              </div>
              <div className={styles.stepLabel}>{step.label}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
