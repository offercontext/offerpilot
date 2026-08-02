import { useEffect, useState } from 'react';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Button, Empty, Table } from 'antd';
import type { Offer, OfferComparisonRead } from '@/types/offer';
import { OFFER_STATUS_LABELS } from '@/types/offer';
import { readOfferComparison } from '@/services/offers';

interface Props {
  open: boolean;
  onClose: () => void;
  offers: Offer[];
  dimensionIds?: number[];
  onCoach?: (offer: Offer) => void;
  onNegotiation?: (offer: Offer) => void;
}

interface Row {
  key: string;
  field: string;
  [companyKey: string]: string | number;
}

function formatWan(value: number): string {
  return `${(value / 10000).toFixed(1)} 万元`;
}

export default function OfferCompareDrawer({
  open,
  onClose,
  offers,
  dimensionIds = [],
  onCoach,
  onNegotiation,
}: Props) {
  const [comparison, setComparison] = useState<OfferComparisonRead | null>(null);

  useEffect(() => {
    if (!open || offers.length < 2) {
      setComparison(null);
      return;
    }
    let current = true;
    void readOfferComparison(offers.map((offer) => offer.id), dimensionIds)
      .then((payload) => { if (current) setComparison(payload); })
      .catch(() => { if (current) setComparison(null); });
    return () => { current = false; };
  }, [open, offers, dimensionIds]);

  if (!open) return null;
  const displayedOffers = comparison?.offers ?? offers;
  const columns = [
    { title: '维度', dataIndex: 'field', key: 'field', fixed: 'left' as const, width: 120 },
    ...displayedOffers.map((offer) => ({
      title: offer.company_name,
      dataIndex: `c${offer.id}`,
      key: `c${offer.id}`,
    })),
  ];

  const fieldRow = (field: string, value: (offer: Offer) => string | number): Row => {
    const row: Row = { key: field, field };
    displayedOffers.forEach((offer) => { row[`c${offer.id}`] = value(offer); });
    return row;
  };

  const data: Row[] = [
    fieldRow('职位', (offer) => offer.position_name || '尚未填写'),
    fieldRow('状态', (offer) => OFFER_STATUS_LABELS[offer.status]),
    fieldRow('月薪与月数', (offer) => `${offer.base_monthly / 1000}K × ${offer.months_per_year}`),
    fieldRow('签字费', (offer) => offer.signing_bonus > 0 ? formatWan(offer.signing_bonus) : '尚未填写'),
    fieldRow('年总包事实', (offer) => formatWan(offer.total_cash)),
    fieldRow('期权', (offer) => offer.equity || '尚未填写'),
    fieldRow('福利', (offer) => offer.perks || '尚未填写'),
    fieldRow('截止时间', (offer) => offer.deadline || '尚未填写'),
  ];
  if (comparison) {
    for (const dimension of comparison.dimensions) {
      data.push(fieldRow(dimension.label, (offer) => {
        const cell = dimension.values.find((value) => value.offer_id === offer.id);
        return cell?.value_text || '尚未填写';
      }));
    }
  }

  return (
    <section aria-label="Offer 横向对比" data-selected-dimension-ids={dimensionIds.join(',')}>
      <div style={{ display: 'grid', gap: 8, marginBottom: 18 }}>
        <Button type="link" icon={<ArrowLeftOutlined />} onClick={onClose} style={{ width: 'fit-content', height: 'auto', padding: 0 }}>
          返回 Offer 中心
        </Button>
        <h2 style={{ margin: 0 }}>Offer 横向对比</h2>
      </div>
      {displayedOffers.length === 0 ? (
        <Empty description="请选择至少两个 Offer" />
      ) : (
        <>
          <Table columns={columns} dataSource={data} pagination={false} scroll={{ x: true }} size="small" bordered />
          {(onNegotiation || onCoach) && (
            <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
              {displayedOffers.map((offer) => (
                <Button key={offer.id} data-action="start-negotiation" data-offer-id={offer.id} onClick={() => (onNegotiation ?? onCoach)?.(offer)}>
                  为 {offer.company_name} 准备谈薪
                </Button>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
