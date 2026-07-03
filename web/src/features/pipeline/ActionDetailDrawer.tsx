import { Button, Drawer, List, Space, Tag, Typography } from 'antd';
import type { ActionCommand, PipelineInsight } from '@/lib/pipelineInsights';
import styles from './pipeline.module.css';

type DetailAction = ActionCommand & { id?: string };

type DetailInsight = PipelineInsight & {
  impact?: string;
  secondaryActions?: DetailAction[];
};

interface Props {
  insight: PipelineInsight | null;
  open: boolean;
  onClose: () => void;
  onRunAction: (insight: PipelineInsight, actionId: string) => void;
}

const PRIORITY_LABEL: Record<PipelineInsight['priority'], string> = {
  p0: 'P0',
  p1: 'P1',
  p2: 'P2',
};

function getActionId(action: DetailAction, fallback: string) {
  return action.id ?? fallback;
}

export default function ActionDetailDrawer({ insight, open, onClose, onRunAction }: Props) {
  const detail = insight as DetailInsight | null;
  const primaryAction = detail?.primaryAction as DetailAction | undefined;
  const secondaryActions = detail?.secondaryActions ?? [];

  const title = detail?.title ? (
    <Space size={8} wrap>
      <Tag color={detail.priority === 'p0' ? 'red' : detail.priority === 'p1' ? 'orange' : 'blue'}>
        {PRIORITY_LABEL[detail.priority]}
      </Tag>
      <Typography.Text strong>{detail.title}</Typography.Text>
    </Space>
  ) : (
    'Pipeline action'
  );

  return (
    <Drawer title={title} open={open} onClose={onClose} width={560} destroyOnClose>
      {detail && primaryAction ? (
        <div className={styles.drawerBody}>
          <section className={styles.section}>
            <Typography.Title level={5}>Why this appears</Typography.Title>
            <Typography.Paragraph>{detail.reason}</Typography.Paragraph>
            {detail.evidence.length > 0 && (
              <List
                size="small"
                dataSource={detail.evidence}
                renderItem={(item) => <List.Item>{item}</List.Item>}
              />
            )}
          </section>

          {detail.impact && (
            <section className={styles.section}>
              <Typography.Title level={5}>Impact</Typography.Title>
              <Typography.Paragraph>{detail.impact}</Typography.Paragraph>
            </section>
          )}

          <section className={styles.section}>
            <Typography.Title level={5}>Recommended next step</Typography.Title>
            <Space direction="vertical" size={12}>
              <Button type="primary" onClick={() => onRunAction(detail, getActionId(primaryAction, 'primary'))}>
                {primaryAction.label}
              </Button>
              {secondaryActions.length > 0 && (
                <div className={styles.secondaryActions}>
                  {secondaryActions.map((action, index) => (
                    <Button
                      key={getActionId(action, `secondary-${index}`)}
                      onClick={() => onRunAction(detail, getActionId(action, `secondary-${index}`))}
                    >
                      {action.label}
                    </Button>
                  ))}
                </div>
              )}
            </Space>
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}
