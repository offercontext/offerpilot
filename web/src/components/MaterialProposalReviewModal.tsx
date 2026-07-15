import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Checkbox, Modal, Space, Tag, Typography } from 'antd';
import { isAxiosError } from 'axios';
import type { MaterialRevisionProposal } from '@/types/materialRevisionProposal';
import { acceptMaterialRevisionProposal, rejectMaterialRevisionProposal } from '@/services/materialRevisionProposals';
import styles from './MaterialProposalReviewModal.module.css';

interface Props {
  applicationID: number;
  proposal: MaterialRevisionProposal | null;
  open: boolean;
  onClose: () => void;
  onAccepted: () => void;
}

function evidenceLabel(source: string): string {
  if (source === 'user_assertion') return 'User assertion supplied for this proposal';
  if (source === 'evidence_bundle') return 'Confirmed application evidence snapshot';
  return 'Source resume';
}

function errorMessage(error: unknown): string {
  if (isAxiosError(error) && error.response?.status === 409) {
    return 'The source changed while this proposal was open. Review and generate a new proposal.';
  }
  if (error instanceof Error && error.message) return error.message;
  return 'The proposal could not be updated. Please retry.';
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
      if (isAxiosError(reason) && reason.response?.status === 409) setSourceConflict(true);
      setError(errorMessage(reason));
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
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Modal
        open={open}
        title="AI recommendation — human review required"
        onCancel={busy ? undefined : onClose}
        destroyOnClose
        footer={(
          <Space>
            <Button onClick={handleReject} disabled={busy}>Reject proposal</Button>
            <Button
              type="primary"
              onClick={() => setConfirmOpen(true)}
              disabled={busy || sourceConflict || selected.length === 0}
            >
              Accept selected changes
            </Button>
          </Space>
        )}
      >
        <div className={styles.body}>
          <Typography.Text className={styles.warning}>
            AI recommendation — human review required. No resume is changed until you accept.
          </Typography.Text>
          <div className={styles.source}>
            <Typography.Text strong>
              {proposal.source.application.company_name} · {proposal.source.application.position_name}
            </Typography.Text>
            <Typography.Text>Source resume: {proposal.source.resume.title}</Typography.Text>
            <Typography.Text>JD direction: {proposal.source.material_kit.jd_excerpt}</Typography.Text>
            <Typography.Text>Proposal generated: {proposal.created_at}</Typography.Text>
          </div>
          <Typography.Paragraph>{proposal.summary}</Typography.Paragraph>
          {proposal.changes.map((change) => (
            <div className={styles.change} key={change.id}>
              <div className={styles.changeHeader}>
                <Checkbox
                  checked={selectedSet.has(change.id)}
                  onChange={(event) => toggleChange(change.id, event.target.checked)}
                  aria-label={`Select ${change.id}`}
                />
                <div className={styles.changeText}>
                  <Typography.Text strong>{change.path}</Typography.Text>
                  <Typography.Text className={styles.before}>Before: {change.before}</Typography.Text>
                  <Typography.Text className={styles.after}>After: {change.after}</Typography.Text>
                  <Typography.Text>Why: {change.rationale}</Typography.Text>
                </div>
              </div>
              <div className={styles.evidenceList}>
                {change.evidence_refs.map((ref) => (
                  <div className={styles.evidence} key={`${change.id}-${ref.source}-${ref.path}`}>
                    <Tag>{evidenceLabel(ref.source)}</Tag>
                    <div>{ref.path}: {ref.excerpt}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {proposal.source.user_assertions.map((assertion) => (
            <Typography.Text key={assertion.id} type="secondary">
              User assertion supplied for this proposal: {assertion.text}
            </Typography.Text>
          ))}
          {error ? <Alert className={styles.error} type="error" showIcon message={error} /> : null}
        </div>
      </Modal>
      <Modal
        open={confirmOpen}
        title="Confirm new derived resume"
        onCancel={() => setConfirmOpen(false)}
        okText="Create derived resume"
        cancelText="Back to review"
        onOk={() => void handleAccept()}
        confirmLoading={busy}
      >
        <Typography.Paragraph>
          This will create a new derived Resume version and update the application Material Kit to point to it. It will not overwrite the source resume.
        </Typography.Paragraph>
      </Modal>
    </>
  );
}
