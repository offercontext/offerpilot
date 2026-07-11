import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Row, Col, Button, Space, Statistic, Spin, Empty, message } from 'antd';
import { PlusOutlined, SwapOutlined } from '@ant-design/icons';
import type { Application } from '@/types/application';
import type { Offer } from '@/types/offer';
import { listOffers } from '@/services/offers';
import OfferCard from '@/components/OfferCard';
import AddOfferForm from '@/components/AddOfferForm';
import OfferCompareDrawer from '@/components/OfferCompareDrawer';
import { findEvidenceFocusRecord } from '@/lib/pilotEvidenceFocus';

interface Props {
  applications: Application[];
  onCoach: (offer: Offer) => void;
  onAttachToPilot?: (attachment: import('@/types/chat').PilotContextAttachment) => void;
  focusOfferId?: number;
  onEvidenceFocusConsumed?: () => void;
}

function wan(n: number): string {
  return (n / 10000).toFixed(1) + '万';
}

export default function OfferCenterView({
  applications,
  onCoach,
  onAttachToPilot,
  focusOfferId,
  onEvidenceFocusConsumed,
}: Props) {
  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<Offer | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  const { data: offers = [], isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ['offers'],
    queryFn: () => listOffers(),
  });

  useEffect(() => {
    if (focusOfferId === undefined || isLoading || isError || isFetching) return;
    const offer = findEvidenceFocusRecord(offers, focusOfferId);
    if (offer) {
      setCompareOpen(false);
      setEditing(offer);
      setAddOpen(true);
    } else {
      message.warning('引用的记录已不存在');
    }
    onEvidenceFocusConsumed?.();
  }, [focusOfferId, isLoading, isError, isFetching, offers, onEvidenceFocusConsumed]);

  const stats = useMemo(() => {
    if (offers.length === 0) return { avg: 0, maxSigning: 0 };
    const avg = offers.reduce((s, o) => s + o.total_cash, 0) / offers.length;
    const maxSigning = Math.max(...offers.map((o) => o.signing_bonus));
    return { avg, maxSigning };
  }, [offers]);

  const toggleSelect = (id: number) =>
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const selectedOffers = offers.filter((o) => selectedIds.includes(o.id));

  if (isLoading) {
    return (
      <div role="status" style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
        <div>正在加载 Offer</div>
      </div>
    );
  }

  if (isError) {
    return (
      <div role="alert" style={{ textAlign: 'center', padding: 48 }}>
        <Empty description="加载 Offer 失败">
          <Button onClick={() => void refetch()}>重试</Button>
        </Empty>
      </div>
    );
  }

  if (compareOpen) {
    return (
      <OfferCompareDrawer
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
        offers={selectedOffers}
      />
    );
  }

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space size="large">
            <Statistic title="Offer 总数" value={offers.length} />
            <Statistic title="平均年总包" value={offers.length ? wan(stats.avg) : '—'} />
            <Statistic title="最高签字费" value={offers.length ? wan(stats.maxSigning) : '—'} />
          </Space>
        </Col>
        <Col>
          <Space>
            <Button
              icon={<SwapOutlined />}
              disabled={selectedIds.length < 1}
              onClick={() => setCompareOpen(true)}
            >
              对比选中 ({selectedIds.length})
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                setEditing(null);
                setAddOpen(true);
              }}
            >
              录入 Offer
            </Button>
          </Space>
        </Col>
      </Row>

      {offers.length === 0 ? (
        <Empty description="还没有 offer，点击「录入 Offer」开始" />
      ) : (
        <Row gutter={[16, 16]}>
          {offers.map((offer) => (
            <Col key={offer.id} xs={24} sm={12} md={8}>
              <OfferCard
                offer={offer}
                selected={selectedIds.includes(offer.id)}
                onToggleSelect={toggleSelect}
                onCoach={onCoach}
                onAttachToPilot={onAttachToPilot}
                onView={(o) => {
                  setEditing(o);
                  setAddOpen(true);
                }}
              />
            </Col>
          ))}
        </Row>
      )}

      <AddOfferForm
        open={addOpen}
        onClose={() => setAddOpen(false)}
        applications={applications}
        editing={editing}
      />
    </div>
  );
}
