import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Checkbox, Modal, Space, Tag, Typography } from 'antd';
import type { MaterialRevisionProposal } from '@/types/materialRevisionProposal';
import { acceptMaterialRevisionProposal, rejectMaterialRevisionProposal } from '@/services/materialRevisionProposals';
import {
  isMaterialFlowSourceConflict,
  MATERIAL_FLOW_COPY,
  materialEvidenceSourceLabel,
  materialFlowErrorMessage,
} from './materialFlowCopy';
import styles from './MaterialProposalReviewModal.module.css';

interface Props {
  applicationID: number;
  proposal: MaterialRevisionProposal | null;
  open: boolean;
  onClose: () => void;
  onAccepted: () => void;
}

export default function MaterialProposalReviewModal({
  applicationID,
  proposal,
  open,
  onClose,
  onAccepted,
}: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceConflict, setSourceConflict] = useState(false);

  useEffect(() => {
    if (!proposal) return;
    setSelected(proposal.changes.map((change) => change.id));
    setConfirmOpen(false);
    setError(null);
    setSourceConflict(false);
  }, [proposal?.id]);

  const selectedSet = useMemo(() => new Set(selected), [selected]);

  if (!proposal) return null;

  const toggleChange = (id: string, checked: boolean) => {
    setSelected((current) => checked ? [...current, id] : current.filter((value) => value !== id));
    if (!sourceConflict) setError(null);
  };

  const handleAccept = async () => {
    setBusy(true);
    setError(null);
    try {
      await acceptMaterialRevisionProposal(applicationID, proposal.id, {
        expected_proposal_sha256: proposal.proposal_sha256,
        selected_change_ids: selected,
      });
      setConfirmOpen(false);
      onAccepted();
    } catch (reason) {
      if (isMaterialFlowSourceConflict(reason)) setSourceConflict(true);
      setError(materialFlowErrorMessage(reason, 'proposal'));
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    setBusy(true);
    setError(null);
    try {
      await rejectMaterialRevisionProposal(applicationID, proposal.id);
      onClose();
    } catch (reason) {
      setError(materialFlowErrorMessage(reason, 'proposal'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Modal
        open={open}
        title={MATERIAL_FLOW_COPY.proposal.title}
        onCancel={busy ? undefined : onClose}
        destroyOnClose
        footer={(
          <Space>
            <Button onClick={handleReject} disabled={busy}>{MATERIAL_FLOW_COPY.proposal.reject}</Button>
            <Button
              type="primary"
              onClick={() => setConfirmOpen(true)}
              disabled={busy || sourceConflict || selected.length === 0}
            >
              {MATERIAL_FLOW_COPY.proposal.accept}
            </Button>
          </Space>
        )}
      >
        <div className={styles.body}>
          <Typography.Text className={styles.warning}>
            {MATERIAL_FLOW_COPY.proposal.warning}
          </Typography.Text>
          <div className={styles.source}>
            <Typography.Text strong>
              {proposal.source.application.company_name} · {proposal.source.application.position_name}
            </Typography.Text>
            <Typography.Text>{MATERIAL_FLOW_COPY.proposal.sourceResume}：{proposal.source.resume.title}</Typography.Text>
            <Typography.Text>{MATERIAL_FLOW_COPY.proposal.jdDirection}：{proposal.source.material_kit.jd_excerpt}</Typography.Text>
            <Typography.Text>{MATERIAL_FLOW_COPY.proposal.generatedAt}：{proposal.created_at}</Typography.Text>
          </div>
          {proposal.changes.length === 0 ? (
            <Alert type="info" showIcon message={MATERIAL_FLOW_COPY.proposal.empty} />
          ) : (
            <>
              <Typography.Paragraph>{proposal.summary}</Typography.Paragraph>
              {proposal.changes.map((change) => (
                <div className={styles.change} key={change.id}>
                  <div className={styles.changeHeader}>
                    <Checkbox
                      checked={selectedSet.has(change.id)}
                      onChange={(event) => toggleChange(change.id, event.target.checked)}
                      aria-label={MATERIAL_FLOW_COPY.proposal.selectChange(change.id)}
                    />
                    <div className={styles.changeText}>
                      <Typography.Text strong>{change.path}</Typography.Text>
                      <Typography.Text className={styles.before}>{MATERIAL_FLOW_COPY.proposal.before}：{change.before}</Typography.Text>
                      <Typography.Text className={styles.after}>{MATERIAL_FLOW_COPY.proposal.after}：{change.after}</Typography.Text>
                      <Typography.Text>{MATERIAL_FLOW_COPY.proposal.why}：{change.rationale}</Typography.Text>
                    </div>
                  </div>
                  <div className={styles.evidenceList}>
                    {change.evidence_refs.map((ref) => (
                      <div className={styles.evidence} key={`${change.id}-${ref.source}-${ref.path}`}>
                        <Tag>{materialEvidenceSourceLabel(ref.source)}</Tag>
                        <div>{ref.path}: {ref.excerpt}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}
          {proposal.source.user_assertions.map((assertion) => (
            <Typography.Text key={assertion.id} type="secondary">
              {MATERIAL_FLOW_COPY.proposal.userAssertion}：{assertion.text}
            </Typography.Text>
          ))}
          {error ? <Alert className={styles.error} type="error" showIcon message={error} /> : null}
        </div>
      </Modal>
      <Modal
        open={confirmOpen}
        title={MATERIAL_FLOW_COPY.proposal.confirmTitle}
        onCancel={() => setConfirmOpen(false)}
        okText={MATERIAL_FLOW_COPY.proposal.createDerivedResume}
        cancelText={MATERIAL_FLOW_COPY.proposal.backToReview}
        onOk={() => void handleAccept()}
        confirmLoading={busy}
      >
        <Typography.Paragraph>
          {MATERIAL_FLOW_COPY.proposal.confirmBody}
        </Typography.Paragraph>
      </Modal>
    </>
  );
}
