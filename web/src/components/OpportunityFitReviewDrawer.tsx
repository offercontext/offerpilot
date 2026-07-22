import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  Divider,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { listResumes } from '@/services/resumes';
import {
  createOpportunityFitDeepReview,
  createOpportunityFitReview,
  getOpportunityFitReview,
  listOpportunityFitReviews,
} from '@/services/opportunityFitReviews';
import type { Application } from '@/types/application';
import type { Resume } from '@/types/resume';
import type {
  OpportunityFitEvidenceRef,
  OpportunityFitReview,
} from '@/types/opportunityFitReview';
import {
  getOpportunityFitErrorMessage,
  OPPORTUNITY_FIT_COPY,
  opportunityFitCandidateStatusLabel,
  opportunityFitConstraintStatusLabel,
  opportunityFitEvidenceLabel,
  opportunityFitGapKindLabel,
  opportunityFitRecommendationColor,
  opportunityFitRecommendationLabel,
  opportunityFitRecommendedPathLabel,
} from './opportunityFitCopy';

interface Props {
  application: Application | null;
  open: boolean;
  onClose: () => void;
  onPrepareMaterials?: (review: OpportunityFitReview, jdText: string) => void;
}

function EvidenceRefs({ refs }: { refs: OpportunityFitEvidenceRef[] }) {
  if (refs.length === 0) return <Typography.Text type="secondary">{OPPORTUNITY_FIT_COPY.drawer.noDirectEvidence}</Typography.Text>;
  return (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      {refs.map((ref) => (
        <Typography.Text key={`${ref.source}:${ref.path}:${ref.excerpt}`} type="secondary">
          {opportunityFitEvidenceLabel(ref.source)} · {ref.path} · “{ref.excerpt}”
        </Typography.Text>
      ))}
    </Space>
  );
}

function ReviewItem({
  title,
  statement,
  refs,
}: {
  title?: string;
  statement: string;
  refs: OpportunityFitEvidenceRef[];
}) {
  return (
    <Card size="small" title={title} style={{ marginBottom: 8 }}>
      <Typography.Paragraph>{statement}</Typography.Paragraph>
      <EvidenceRefs refs={refs} />
    </Card>
  );
}

export default function OpportunityFitReviewDrawer({
  application,
  open,
  onClose,
  onPrepareMaterials,
}: Props) {
  const [stage, setStage] = useState<'input' | 'review'>('input');
  const [resumeID, setResumeID] = useState<number>();
  const [jdText, setJdText] = useState('');
  const [assertionsText, setAssertionsText] = useState('');
  const [review, setReview] = useState<OpportunityFitReview | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const reviewHistoryQuery = useQuery({
    queryKey: ['opportunity-fit-reviews', application?.id],
    queryFn: () => listOpportunityFitReviews(application!.id),
    enabled: open && Boolean(application),
  });

  const resumesQuery = useQuery({
    queryKey: ['resumes'],
    queryFn: () => listResumes(),
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    setStage('input');
    setResumeID(undefined);
    setJdText('');
    setAssertionsText('');
    setReview(null);
    setActionError(null);
  }, [application?.id, open]);

  const assertions = useMemo(
    () => assertionsText.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
    [assertionsText],
  );
  const assertionError = assertions.length > 10
    ? OPPORTUNITY_FIT_COPY.drawer.assertionsTooMany
    : assertions.some((value) => value.length > 500)
      ? OPPORTUNITY_FIT_COPY.drawer.assertionsTooLong
      : null;

  const createMutation = useMutation({
    mutationFn: () => createOpportunityFitReview(application!.id, {
      resume_id: resumeID!,
      jd_text: jdText.trim(),
      jd_source_label: OPPORTUNITY_FIT_COPY.drawer.jdSourceLabel,
      candidate_assertions: assertions,
      idempotency_key: crypto.randomUUID(),
    }),
    onSuccess: (nextReview) => {
      setReview(nextReview);
      setStage('review');
      setActionError(null);
    },
    onError: (error) => setActionError(getOpportunityFitErrorMessage(error)),
  });

  const deepReviewMutation = useMutation({
    mutationFn: () => createOpportunityFitDeepReview(application!.id, review!.id),
    onSuccess: (nextReview) => {
      setReview(nextReview);
      setActionError(null);
    },
    onError: (error) => setActionError(getOpportunityFitErrorMessage(error)),
  });

  const canSubmit = Boolean(
    application
      && resumeID
      && jdText.trim()
      && !assertionError
      && !createMutation.isPending,
  );

  const submit = () => {
    if (!canSubmit || !resumeID || !jdText.trim() || assertionError) return;
    createMutation.mutate();
  };

  const openHistoricalReview = async (reviewID: number) => {
    if (!application) return;
    try {
      setActionError(null);
      const historicalReview = await getOpportunityFitReview(application.id, reviewID);
      setResumeID(historicalReview.source.resume.id);
      setJdText(historicalReview.source.jd.text);
      setAssertionsText(historicalReview.source.candidate_assertions.map((item) => item.text).join('\n'));
      setReview(historicalReview);
      setStage('review');
    } catch (error) {
      setActionError(getOpportunityFitErrorMessage(error));
    }
  };

  if (!open) return null;

  return (
    <Drawer
      open={open}
      width={680}
      title={OPPORTUNITY_FIT_COPY.drawer.title}
      onClose={onClose}
      destroyOnClose
    >
      <Typography.Paragraph type="secondary">
        {OPPORTUNITY_FIT_COPY.drawer.description}
      </Typography.Paragraph>
      {actionError ? <Alert type="error" showIcon message={actionError} /> : null}

      {stage === 'input' && reviewHistoryQuery.data && reviewHistoryQuery.data.length > 0 ? (
        <Card size="small" title={OPPORTUNITY_FIT_COPY.drawer.history} style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {reviewHistoryQuery.data.map((item) => (
              <Space key={item.id} style={{ justifyContent: 'space-between', width: '100%' }}>
                <Typography.Text>
                  {opportunityFitRecommendationLabel(item.recommendation)} · {new Date(item.created_at).toLocaleString()}
                </Typography.Text>
                <Button size="small" onClick={() => void openHistoricalReview(item.id)}>
                  {OPPORTUNITY_FIT_COPY.drawer.view}
                </Button>
              </Space>
            ))}
          </Space>
        </Card>
      ) : null}

      {stage === 'input' ? (
        <Form layout="vertical">
          <Form.Item label={OPPORTUNITY_FIT_COPY.drawer.resumeLabel} required>
            <Select
              value={resumeID}
              onChange={setResumeID}
              loading={resumesQuery.isFetching}
              placeholder={OPPORTUNITY_FIT_COPY.drawer.resumePlaceholder}
              options={(resumesQuery.data || []).map((resume: Resume) => ({
                value: resume.id,
                label: resume.name || resume.title,
              }))}
            />
          </Form.Item>
          <Form.Item label={OPPORTUNITY_FIT_COPY.drawer.jdLabel} required>
            <Input.TextArea
              value={jdText}
              onChange={(event) => setJdText(event.target.value)}
              rows={9}
              placeholder={OPPORTUNITY_FIT_COPY.drawer.jdPlaceholder}
            />
          </Form.Item>
          <Form.Item label={OPPORTUNITY_FIT_COPY.drawer.assertionsLabel}>
            <Input.TextArea
              value={assertionsText}
              onChange={(event) => setAssertionsText(event.target.value)}
              rows={5}
              placeholder={OPPORTUNITY_FIT_COPY.drawer.assertionsPlaceholder}
            />
            <Typography.Text type="secondary">{OPPORTUNITY_FIT_COPY.drawer.assertionsHint}</Typography.Text>
            {assertionError ? <Typography.Text type="danger">{assertionError}</Typography.Text> : null}
          </Form.Item>
          <Alert
            type="info"
            showIcon
            message={OPPORTUNITY_FIT_COPY.drawer.humanConfirmation}
            description={OPPORTUNITY_FIT_COPY.drawer.humanConfirmationDescription}
          />
          <Button type="primary" onClick={submit} loading={createMutation.isPending} disabled={!canSubmit}>
            {OPPORTUNITY_FIT_COPY.drawer.startTriage}
          </Button>
        </Form>
      ) : review ? (
        <div>
          <Space wrap>
            <Tag color={opportunityFitRecommendationColor(review.recommendation)}>
              {opportunityFitRecommendationLabel(review.recommendation)}
            </Tag>
            <Tag>{OPPORTUNITY_FIT_COPY.drawer.sourceFrozen}</Tag>
            <Tag>{OPPORTUNITY_FIT_COPY.drawer.humanConfirmation}</Tag>
          </Space>
          <Typography.Title level={4}>{OPPORTUNITY_FIT_COPY.drawer.triage}</Typography.Title>
          <Typography.Paragraph>{review.triage.summary.text}</Typography.Paragraph>
          <EvidenceRefs refs={review.triage.summary.evidence_refs} />

          <Typography.Title level={5}>{OPPORTUNITY_FIT_COPY.drawer.hardConstraints}</Typography.Title>
          {review.triage.hard_constraints.map((item) => (
            <ReviewItem
              key={item.id}
              title={`${item.requirement} · ${opportunityFitConstraintStatusLabel(item.status)}`}
              statement={item.explanation}
              refs={item.evidence_refs}
            />
          ))}
          <Typography.Title level={5}>{OPPORTUNITY_FIT_COPY.drawer.fitSignals}</Typography.Title>
          {review.triage.fit_signals.map((item) => (
            <ReviewItem key={item.id} statement={item.statement} refs={item.evidence_refs} />
          ))}
          <Typography.Title level={5}>{OPPORTUNITY_FIT_COPY.drawer.gaps}</Typography.Title>
          {review.triage.gaps.map((item) => (
            <ReviewItem
              key={item.id}
              title={`${opportunityFitGapKindLabel(item.kind)} · ${opportunityFitCandidateStatusLabel(item.candidate_status)}`}
              statement={item.requirement}
              refs={item.evidence_refs}
            />
          ))}
          {review.triage.next_questions.map((question) => (
            <Typography.Paragraph key={question}>？ {question}</Typography.Paragraph>
          ))}
          <Typography.Title level={5}>{OPPORTUNITY_FIT_COPY.drawer.nextQuestions}</Typography.Title>
          <Typography.Paragraph>
            {review.triage.deadline.status === 'stated' ? review.triage.deadline.text : OPPORTUNITY_FIT_COPY.drawer.notStated}
          </Typography.Paragraph>
          <EvidenceRefs refs={review.triage.deadline.evidence_refs} />

          <Divider />
          <Typography.Title level={5}>{OPPORTUNITY_FIT_COPY.drawer.evidenceSources}</Typography.Title>
          <Card size="small">
            <Typography.Text>{OPPORTUNITY_FIT_COPY.drawer.resumeSource}：{review.source.resume.title}</Typography.Text>
            <br />
            <Typography.Text>{OPPORTUNITY_FIT_COPY.drawer.jdSource}：{review.source.jd.source_label}（仅决定分析方向）</Typography.Text>
            {review.source.candidate_assertions.length > 0 ? (
              <>
                <Typography.Paragraph strong>{OPPORTUNITY_FIT_COPY.drawer.candidateAssertions}</Typography.Paragraph>
                {review.source.candidate_assertions.map((assertion) => (
                  <Typography.Paragraph key={assertion.index}>· {assertion.text}</Typography.Paragraph>
                ))}
              </>
            ) : null}
          </Card>

          {review.deep_review ? (
            <>
              <Typography.Title level={4}>{OPPORTUNITY_FIT_COPY.drawer.deepReview}</Typography.Title>
              <Typography.Paragraph>{OPPORTUNITY_FIT_COPY.drawer.recommendedPath}：{opportunityFitRecommendedPathLabel(review.deep_review.recommended_path)}</Typography.Paragraph>
              {review.deep_review.strengths.map((item) => (
                <ReviewItem key={item.id} statement={item.statement} refs={item.evidence_refs} />
              ))}
              {review.deep_review.gaps_to_address.map((item) => (
                <ReviewItem key={item.id} statement={item.statement} refs={item.evidence_refs} />
              ))}
              {review.deep_review.questions_to_clarify.map((item) => (
                <ReviewItem key={item.id} statement={item.statement} refs={item.evidence_refs} />
              ))}
              <Typography.Title level={5}>{OPPORTUNITY_FIT_COPY.drawer.nextActions}</Typography.Title>
              {review.deep_review.next_actions.map((action) => (
                <Card size="small" key={action.id} style={{ marginBottom: 8 }}>
                  <Typography.Text>{action.label}</Typography.Text>
                </Card>
              ))}
              <Button
                type="primary"
                onClick={() => onPrepareMaterials?.(review, review.source.jd.text)}
                disabled={!onPrepareMaterials || !review.source.jd.text}
              >
                {OPPORTUNITY_FIT_COPY.drawer.prepareMaterials}
              </Button>
            </>
          ) : (
            <Button
              type="primary"
              onClick={() => deepReviewMutation.mutate()}
              loading={deepReviewMutation.isPending}
            >
              {OPPORTUNITY_FIT_COPY.drawer.startDeepReview}
            </Button>
          )}
        </div>
      ) : (
        <Spin />
      )}
    </Drawer>
  );
}
