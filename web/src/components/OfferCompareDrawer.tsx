import { ArrowLeftOutlined } from '@ant-design/icons';
import { Button, Empty, Table } from 'antd';
import type { Offer } from '@/types/offer';
import { OFFER_STATUS_LABELS } from '@/types/offer';

interface Props {
  open: boolean;
  onClose: () => void;
  offers: Offer[];
}

interface Row {
  key: string;
  field: string;
  [companyKey: string]: string | number;
}

function wan(n: number): string {
  return (n / 10000).toFixed(1) + '万';
}

export default function OfferCompareDrawer({ open, onClose, offers }: Props) {
  const columns = [
    { title: '维度', dataIndex: 'field', key: 'field', fixed: 'left' as const, width: 120 },
    ...offers.map((o) => ({
      title: `${o.company_name}`,
      dataIndex: `c${o.id}`,
      key: `c${o.id}`,
    })),
  ];

  const fieldRow = (field: string, val: (o: Offer) => string | number): Row => {
    const row: Row = { key: field, field };
    offers.forEach((o) => {
      row[`c${o.id}`] = val(o);
    });
    return row;
  };

  const data: Row[] = [
    fieldRow('岗位', (o) => o.position_name),
    fieldRow('状态', (o) => OFFER_STATUS_LABELS[o.status]),
    fieldRow('月薪×薪数', (o) => `${o.base_monthly / 1000}K×${o.months_per_year}`),
    fieldRow('签字费', (o) => (o.signing_bonus > 0 ? wan(o.signing_bonus) : '无')),
    fieldRow('年总包', (o) => wan(o.total_cash)),
    fieldRow('期权', (o) => o.equity || '无'),
    fieldRow('福利', (o) => o.perks || '无'),
    fieldRow('截止日', (o) => o.deadline || '无'),
  ];

  if (!open) return null;

  return (
    <section aria-label="Offer 横向对比">
      <div style={{ display: 'grid', gap: 8, marginBottom: 18 }}>
        <Button
          type="link"
          icon={<ArrowLeftOutlined />}
          onClick={onClose}
          style={{ width: 'fit-content', height: 'auto', padding: 0 }}
        >
          返回 Offer 中心
        </Button>
        <h2 style={{ margin: 0 }}>Offer 横向对比</h2>
      </div>
      {offers.length === 0 ? (
        <Empty description="请选择至少一个 offer" />
      ) : (
        <Table columns={columns} dataSource={data} pagination={false} scroll={{ x: true }} size="small" bordered />
      )}
    </section>
  );
}
