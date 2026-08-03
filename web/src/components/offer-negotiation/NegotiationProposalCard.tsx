import { useState } from 'react';
import { Checkbox, Input, Tag } from 'antd';
import { OFFER_STATUS_LABELS, type OfferNegotiationBlock } from '@/types/offer';
import styles from './OfferNegotiationPresentation.module.css';

interface Props {
  block: OfferNegotiationBlock;
  selected: boolean;
  editedText: string;
  disabled: boolean;
  onToggle: () => void;
  onEdit: (text: string) => void;
}

function evidenceLabel(path: string): string {
  if (path.endsWith('/base_monthly')) return 'Offer 固定月薪';
  if (path.endsWith('/status')) return 'Offer 状态';
  if (path.endsWith('/goal')) return '用户沟通目标';
  if (path.endsWith('/concerns')) return '用户本次顾虑';
  if (path.endsWith('/scenario')) return '用户沟通场景';
  return '已验证来源';
}

function evidenceExcerpt(path: string, excerpt: string): string {
  if (path.endsWith('/status')) {
    const label = OFFER_STATUS_LABELS[excerpt as keyof typeof OFFER_STATUS_LABELS];
    if (label) return label;
  }
  return excerpt;
}

export default function NegotiationProposalCard({ block, selected, editedText, disabled, onToggle, onEdit }: Props) {
  const [expanded, setExpanded] = useState(false);
  return (
    <article className={`${styles.proposalCard} ${selected ? styles.proposalCardSelected : ''}`} data-selected={selected}>
      <div className={styles.proposalMain}>
        <Checkbox checked={selected} disabled={disabled} onChange={onToggle}>{block.text}</Checkbox>
        <Tag>{block.rationale}</Tag>
      </div>
      <p className={styles.rationale}><strong>为什么建议：</strong>{block.rationale}</p>
      {selected && <Input.TextArea aria-label="编辑谈薪建议" value={editedText} disabled={disabled} onChange={(event) => onEdit(event.target.value)} autoSize={{ minRows: 2, maxRows: 5 }} />}
      <div className={styles.evidenceSummary}>
        {block.evidence_refs.map((ref) => (
          <span key={`${ref.source}-${ref.path}`}>{evidenceLabel(ref.path)}：{evidenceExcerpt(ref.path, ref.excerpt)}</span>
        ))}
      </div>
      <button type="button" className={styles.evidenceToggle} data-action="toggle-evidence" aria-expanded={expanded} onClick={() => setExpanded((current) => !current)}>
        {expanded ? '收起证据路径' : '查看证据路径'}
      </button>
      {expanded && <div className={styles.rawEvidence}>{block.evidence_refs.map((ref) => <code key={`${ref.source}-${ref.path}`}>{ref.path}: {evidenceExcerpt(ref.path, ref.excerpt)}</code>)}</div>}
    </article>
  );
}
