import { Card, Tag, Button, Checkbox, Space, Typography } from 'antd';
import { MessageOutlined, EyeOutlined } from '@ant-design/icons';
import type { Offer } from '@/types/offer';
import { OFFER_STATUS_LABELS, OFFER_STATUS_COLORS } from '@/types/offer';

const { Text } = Typography;

interface Props {
  offer: Offer;
  selected: boolean;
  onToggleSelect: (id: number) => void;
  onCoach: (offer: Offer) => void;
  onView: (offer: Offer) => void;
}

function formatWan(n: number): string {
  return (n / 10000).toFixed(1) + '万';
}

export default function OfferCard({ offer, selected, onToggleSelect, onCoach, onView }: Props) {
  return (
    <Card
      size="small"
      style={{ borderColor: OFFER_STATUS_COLORS[offer.status] }}
      title={
        <Space>
          <Checkbox checked={selected} onChange={() => onToggleSelect(offer.id)} />
          <Text strong>{offer.company_name}</Text>
        </Space>
      }
      extra={<Tag color={OFFER_STATUS_COLORS[offer.status]}>{OFFER_STATUS_LABELS[offer.status]}</Tag>}
    >
      <div style={{ color: '#374151' }}>{offer.position_name}</div>
      <div style={{ fontSize: 20, fontWeight: 700, margin: '4px 0' }}>
        {offer.base_monthly / 1000}K×{offer.months_per_year}
      </div>
      <div style={{ color: '#6b7280', fontSize: 12, lineHeight: 1.6 }}>
        签字费 {offer.signing_bonus > 0 ? formatWan(offer.signing_bonus) : '无'}
        {offer.equity ? ` · 期权 ${offer.equity}` : ''}
        <br />
        年总包约 {formatWan(offer.total_cash)}
        {offer.deadline ? ` · 截止 ${offer.deadline}` : ''}
        {offer.application_id ? ` · 关联投递 #${offer.application_id}` : ' · 无关联投递'}
      </div>
      <Space style={{ marginTop: 8 }}>
        <Button type="primary" size="small" icon={<MessageOutlined />} onClick={() => onCoach(offer)}>
          谈薪教练
        </Button>
        <Button size="small" icon={<EyeOutlined />} onClick={() => onView(offer)}>
          详情
        </Button>
      </Space>
    </Card>
  );
}
