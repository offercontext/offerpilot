import { createElement } from 'react';
import { Switch } from 'antd';
import type { Offer } from '@/types/offer';
import { OFFER_STATUS_LABELS, OFFER_STATUS_COLORS } from '@/types/offer';
import type { Capability } from './capabilities';
import type { EvidenceItem } from './model';
import EvidenceList from './EvidenceList';
import styles from './ChatPanel.module.css';

interface Props {
  floating?: boolean;
  isNego: boolean;
  offer: Offer | null;
  capabilities: Capability[];
  evidence: EvidenceItem[];
  autoApprove: boolean;
  hasKey: boolean;
  degraded: boolean;
  disabled: boolean;
  onCapability: (cap: Capability) => void;
  onToggleAutoApprove: (v: boolean) => void;
  onOpenSettings?: () => void;
}

function formatTotal(total: number): string {
  if (total >= 10000) return (total / 10000).toFixed(1);
  return String(total);
}

export default function ContextPanel({
  floating,
  isNego,
  offer,
  capabilities,
  evidence,
  autoApprove,
  hasKey,
  degraded,
  disabled,
  onCapability,
  onToggleAutoApprove,
  onOpenSettings,
}: Props) {
  return (
    <aside className={`${styles.context} ${floating ? styles.contextFloating : ''}`}>
      {isNego && offer && (
        <div>
          <div className={styles.panelLabel}>当前绑定 Offer</div>
          <div className={styles.offerCard}>
            <div className={styles.offerCompany}>{offer.company_name}</div>
            <div className={styles.offerRole}>{offer.position_name}</div>
            <div className={styles.offerTotal}>
              {formatTotal(offer.total_cash)}
              <span className={styles.offerUnit}>w 总包/年</span>
            </div>
            <span
              className={styles.offerStatus}
              style={{
                color: OFFER_STATUS_COLORS[offer.status],
                background: `${OFFER_STATUS_COLORS[offer.status]}1f`,
              }}
            >
              {OFFER_STATUS_LABELS[offer.status]}
            </span>
          </div>
        </div>
      )}

      <div>
        <div className={styles.panelLabel}>当前参考依据</div>
        {evidence.length ? (
          <EvidenceList items={evidence.slice(0, 5)} clamped />
        ) : (
          <div className={styles.evidenceEmpty}>
            暂无参考依据。你可以直接提问，或选择一个能力，让领航员读取本地求职数据。
          </div>
        )}
      </div>

      <div>
        <div className={styles.panelLabel}>{isNego ? '谈薪教练能力' : '常用能力'}</div>
        <div className={styles.capList}>
          {capabilities.map((cap) => {
            return (
              <button
                key={cap.id}
                type="button"
                className={styles.capItem}
                disabled={disabled}
                onClick={() => onCapability(cap)}
                title={cap.hint}
              >
                <span className={styles.capIcon} aria-hidden="true">
                  {createElement(cap.icon)}
                </span>
                {cap.label}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <div className={styles.panelLabel}>设置</div>
        <label className={styles.setting}>
          <span>本地写入自动确认</span>
          <Switch checked={autoApprove} onChange={onToggleAutoApprove} />
        </label>
      </div>

      {!hasKey && (
        <div className={`${styles.notice} ${styles.noticeWarn}`}>
          尚未配置 API key，请先完成 AI 设置。
          {onOpenSettings && (
            <button type="button" className={styles.noticeAction} onClick={onOpenSettings}>
              打开 AI 设置
            </button>
          )}
        </div>
      )}
      {degraded && (
        <div className={styles.notice}>
          当前模型不支持工具调用，已切换为只读摘要模式，AI 无法修改你的数据。
        </div>
      )}
      <div className={styles.notice}>
        领航员可读取并修改你的投递、日程、复盘与 Offer。删除等高风险写入始终需要你手动确认。
      </div>
    </aside>
  );
}
