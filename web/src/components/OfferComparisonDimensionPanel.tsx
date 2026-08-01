import { useEffect, useState } from 'react';
import type { Offer, OfferComparisonDimension } from '@/types/offer';
import {
  clearOfferComparisonValue,
  createOfferComparisonDimension,
  listOfferComparisonDimensions,
  listOfferComparisonValues,
  saveOfferComparisonValue,
  updateOfferComparisonDimension,
} from '@/services/offers';

interface Props {
  offers: Offer[];
  onSelectionChange?: (dimensionIds: number[]) => void;
}

export default function OfferComparisonDimensionPanel({ offers, onSelectionChange }: Props) {
  const [dimensions, setDimensions] = useState<OfferComparisonDimension[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [draftLabel, setDraftLabel] = useState('');
  const [draftValues, setDraftValues] = useState<Record<string, string>>({});

  const reload = async () => {
    const [nextDimensions, valueLists] = await Promise.all([
      listOfferComparisonDimensions(true),
      Promise.all(offers.map((offer) => listOfferComparisonValues(offer.id))),
    ]);
    setDimensions(nextDimensions);
    const nextValues: Record<string, string> = {};
    valueLists.flat().forEach((value) => {
      nextValues[`${value.offer_id}:${value.dimension_id}`] = value.value_text ?? '';
    });
    setDraftValues(nextValues);
    setSelectedIds((current) => current.filter((id) => nextDimensions.some((dimension) => dimension.id === id && dimension.archived_at === null)));
  };

  useEffect(() => {
    void reload();
    // The panel intentionally refreshes only when the Offer set changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offers.map((offer) => offer.id).join(',')]);

  const selectDimension = (id: number, checked: boolean) => {
    const next = checked
      ? [...selectedIds, id].sort((left, right) => left - right)
      : selectedIds.filter((item) => item !== id);
    setSelectedIds(next);
    onSelectionChange?.(next);
  };

  const createDimension = async () => {
    if (!draftLabel.trim()) return;
    const created = await createOfferComparisonDimension(draftLabel);
    setDimensions((current) => [...current, created].sort((left, right) => left.id - right.id));
    setDraftLabel('');
  };

  const archiveDimension = async (id: number) => {
    const updated = await updateOfferComparisonDimension(id, { archived: true });
    setDimensions((current) => current.map((dimension) => dimension.id === id ? updated : dimension));
    setSelectedIds((current) => current.filter((item) => item !== id));
  };

  const saveValue = async (offerId: number, dimensionId: number) => {
    const value = draftValues[`${offerId}:${dimensionId}`] ?? '';
    if (!value.trim()) return;
    const saved = await saveOfferComparisonValue(offerId, dimensionId, value);
    setDraftValues((current) => ({ ...current, [`${saved.offer_id}:${saved.dimension_id}`]: saved.value_text ?? '' }));
  };

  const clearValue = async (offerId: number, dimensionId: number) => {
    await clearOfferComparisonValue(offerId, dimensionId);
    setDraftValues((current) => ({ ...current, [`${offerId}:${dimensionId}`]: '' }));
  };

  return (
    <section aria-label="自定义比较维度" style={{ margin: '16px 0', padding: 16, border: '1px solid #e5e7eb', borderRadius: 8 }}>
      <h3 style={{ marginTop: 0 }}>管理比较维度</h3>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          aria-label="新比较维度"
          placeholder="新比较维度"
          value={draftLabel}
          onChange={(event) => setDraftLabel(event.target.value)}
        />
        <button type="button" data-action="create-dimension" onClick={() => void createDimension()}>新增维度</button>
      </div>
      <p style={{ color: '#6b7280' }}>最多选择 8 个比较维度。空白值表示尚未填写。</p>
      {dimensions.map((dimension) => {
        const active = dimension.archived_at === null;
        return (
          <div key={dimension.id} data-dimension-id={dimension.id} style={{ padding: '8px 0', borderTop: '1px solid #f3f4f6' }}>
            <label>
              {active && (
                <input
                  type="checkbox"
                  checked={selectedIds.includes(dimension.id)}
                  disabled={!selectedIds.includes(dimension.id) && selectedIds.length >= 8}
                  onChange={(event) => selectDimension(dimension.id, event.target.checked)}
                />
              )}
              <span style={{ marginLeft: 8 }}>{dimension.label}</span>
              {!active && <span style={{ marginLeft: 8, color: '#6b7280' }}>已归档（仅历史可读）</span>}
            </label>
            {active && (
              <div style={{ margin: '8px 0 0 24px' }}>
                {offers.map((offer) => {
                  const key = `${offer.id}:${dimension.id}`;
                  return (
                    <div key={key} style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                      <span style={{ width: 110 }}>{offer.company_name}</span>
                      <input
                        data-offer-id={offer.id}
                        data-dimension-id={dimension.id}
                        aria-label={`${offer.company_name}-${dimension.label}`}
                        value={draftValues[key] ?? ''}
                        placeholder="尚未填写"
                        onChange={(event) => setDraftValues((current) => ({ ...current, [key]: event.target.value }))}
                      />
                      <button type="button" data-action="save-value" data-offer-id={offer.id} onClick={() => void saveValue(offer.id, dimension.id)}>保存</button>
                      <button type="button" data-action="clear-value" data-offer-id={offer.id} onClick={() => void clearValue(offer.id, dimension.id)}>清除值</button>
                    </div>
                  );
                })}
                <button type="button" data-action="archive-dimension" data-dimension-id={dimension.id} onClick={() => void archiveDimension(dimension.id)}>归档维度</button>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
