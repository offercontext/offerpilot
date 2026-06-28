import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Layout, Button, Typography, Spin, Statistic, Row, Col, Space } from 'antd';
import { PlusOutlined, FileTextOutlined } from '@ant-design/icons';
import { listApplications } from '@/services/applications';
import { KANBAN_COLUMNS, STATUS_LABELS } from '@/types/application';
import type { Application, ApplicationStatus } from '@/types/application';
import KanbanBoard from '@/components/KanbanBoard';
import AddApplicationForm from '@/components/AddApplicationForm';
import ApplicationDetail from '@/components/ApplicationDetail';
import ResumeMatchModal from '@/components/ResumeMatchModal';

const { Header, Content } = Layout;
const { Title } = Typography;

export default function App() {
  const [addOpen, setAddOpen] = useState(false);
  const [resumeOpen, setResumeOpen] = useState(false);
  const [selected, setSelected] = useState<Application | null>(null);

  const { data: applications = [], isLoading } = useQuery({
    queryKey: ['applications'],
    queryFn: () => listApplications(),
  });

  const stats = useMemo(() => {
    const counts = {} as Record<ApplicationStatus, number>;
    for (const s of KANBAN_COLUMNS) counts[s] = 0;
    applications.forEach((app) => {
      if (counts[app.status] !== undefined) counts[app.status]++;
    });
    return counts;
  }, [applications]);

  // Keep the open-drawer record in sync with latest cache data.
  const selectedApp = selected
    ? applications.find((a) => a.id === selected.id) ?? selected
    : null;

  return (
    <Layout style={{ minHeight: '100vh', background: '#f0f4f8' }}>
      <Header
        style={{
          background: '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 24px',
          borderBottom: '1px solid #e2e8f0',
        }}
      >
        <Title level={4} style={{ margin: 0, color: '#059669' }}>
          🚀 OfferPilot
        </Title>
        <Space>
          <Button icon={<FileTextOutlined />} onClick={() => setResumeOpen(true)}>
            简历匹配
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
            添加投递
          </Button>
        </Space>
      </Header>

      <Content style={{ padding: 24 }}>
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col>
            <Statistic title="投递总数" value={applications.length} />
          </Col>
          {KANBAN_COLUMNS.map((status) => (
            <Col key={status}>
              <Statistic title={STATUS_LABELS[status]} value={stats[status]} />
            </Col>
          ))}
        </Row>

        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin size="large" />
          </div>
        ) : (
          <KanbanBoard
            applications={applications}
            onOpenDetail={(app) => setSelected(app)}
          />
        )}
      </Content>

      <AddApplicationForm open={addOpen} onClose={() => setAddOpen(false)} />
      <ApplicationDetail
        application={selectedApp}
        open={!!selected}
        onClose={() => setSelected(null)}
      />
      <ResumeMatchModal open={resumeOpen} onClose={() => setResumeOpen(false)} />
    </Layout>
  );
}