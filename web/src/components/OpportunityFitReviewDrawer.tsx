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
  createOpportunityFitV2Triage,
  confirmOpportunityFitV2Triage,
  createOpportunityFitV2DeepReview,
  getOpportunityFitReview,
  getOpportunityFitV2Review,
  listOpportunityFitReviews,
  listOpportunityFitV2Reviews,
} from '@/services/opportunityFitReviews';
import type { Application } from '@/types/application';
import type { Resume } from '@/types/resume';
import type {
  OpportunityFitEvidenceRef,
  OpportunityFitReview,
  OpportunityFitV2EvidenceRef,
  OpportunityFitV2Proposal,
  OpportunityFitV2StageResponse,
} from '@/types/opportunityFitReview';
import {
  getOpportunityFitErrorMessage,
  OPPORTUNITY_FIT_COPY,
  opportunityFitEvidenceLabel,
  opportunityFitGapKindLabel,
  opportunityFitRecommendationColor,
  opportunityFitRecommendationLabel,
  opportunityFitRecommendedPathLabel,
  opportunityFitStatusLabel,
} from './opportunityFitCopy';
import { SourceStateTag } from './ui/SourceStateTag';

interface Props {
  application: Application | null;
  open: boolean;
  currentJdText?: string;
  jdVersionId?: number | null;
  onClose: () => void;
  onPrepareMaterials?: (reviewOrResumeId: OpportunityFitReview | number, jdText: string, jdVersionId?: number) => void;
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

function V2EvidenceRefs({ refs }: { refs: OpportunityFitV2EvidenceRef[] }) {
  return refs.length > 0 ? (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      {refs.map((ref, index) => (
        <Typography.Text key={`${ref.source}:${ref.path}:${index}`} type="secondary">
          {ref.source} · {ref.path} · “{ref.excerpt}”
        </Typography.Text>
      ))}
    </Space>
  ) : <Typography.Text type="secondary">暂无可验证证据引用</Typography.Text>;
}

function V2ProposalView({ proposal }: { proposal: OpportunityFitV2Proposal }) {
  const sections = [
    ['条件', proposal.conditions],
    ['风险', proposal.risks],
    ['下一步', proposal.next_steps],
  ] as const;
  return (
    <div>
      <Typography.Paragraph>{proposal.summary.text}</Typography.Paragraph>
      <V2EvidenceRefs refs={proposal.summary.evidence_refs} />
      {sections.map(([title, items]) => (
        <section key={title}>
          <Typography.Title level={5}>{title}</Typography.Title>
          {items.length === 0 ? <Typography.Text type="secondary">暂无可验证内容</Typography.Text> : null}
          {items.map((item) => (
            <Card size="small" key={item.id} style={{ marginBottom: 8 }}>
              <Typography.Paragraph>{item.text}</Typography.Paragraph>
              <Typography.Paragraph type="secondary">{item.rationale}</Typography.Paragraph>
              <V2EvidenceRefs refs={item.evidence_refs} />
            </Card>
          ))}
        </section>
      ))}
      <Typography.Title level={5}>待确认问题</Typography.Title>
      {proposal.questions.map((item) => (
        <Card size="small" key={item.question_id} style={{ marginBottom: 8 }}>
          <Typography.Paragraph>{item.text}</Typography.Paragraph>
          <V2EvidenceRefs refs={item.evidence_refs} />
        </Card>
      ))}
    </div>
  );
}

export default function OpportunityFitReviewDrawer({
  application,
  open,
  currentJdText = '',
  jdVersionId,
  onClose,
  onPrepareMaterials,
}: Props) {
  const [stage, setStage] = useState<'input' | 'review'>('input');
  const [resumeID, setResumeID] = useState<number>();
  const [jdText, setJdText] = useState('');
  const [assertionsText, setAssertionsText] = useState('');
  const [review, setReview] = useState<OpportunityFitReview | null>(null);
  const [v2Triage, setV2Triage] = useState<OpportunityFitV2StageResponse | null>(null);
  const [v2Deep, setV2Deep] = useState<OpportunityFitV2StageResponse | null>(null);
  const [v2Historical, setV2Historical] = useState(false);
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
    setV2Triage(null);
    setV2Deep(null);
    setV2Historical(false);
    setActionError(null);
  }, [application?.id, open]);

  useEffect(() => {
    if (!open || stage !== 'input' || v2Triage || v2Deep || v2Historical) return;
    setJdText(currentJdText);
  }, [currentJdText, open, stage, v2Deep, v2Historical, v2Triage]);

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
    mutationFn: () => createOpportunityFitV2Triage(application!.id, {
      schema_version: 2,
      resume_id: resumeID!,
      jd_version_id: jdVersionId ?? 0,
      jd_source_label: OPPORTUNITY_FIT_COPY.drawer.jdSourceLabel,
      candidate_assertions: assertions,
      idempotency_key: crypto.randomUUID(),
    }),
    onSuccess: (nextReview) => {
      setV2Triage(nextReview);
      setV2Deep(null);
      setStage('review');
      setActionError(null);
    },
    onError: (error) => setActionError(getOpportunityFitErrorMessage(error)),
  });
  const v2HistoryQuery = useQuery({
    queryKey: ['opportunity-fit-v2-reviews', application?.id],
    queryFn: () => listOpportunityFitV2Reviews(application!.id),
    enabled: open && Boolean(application),
  });

  const confirmV2Mutation = useMutation({
    mutationFn: () => confirmOpportunityFitV2Triage(
      application!.id,
      v2Triage!.review_id,
      v2Triage!.stage_id,
      v2Triage!.confirmation_token!,
    ),
    onSuccess: setV2Triage,
    onError: (error) => setActionError(getOpportunityFitErrorMessage(error)),
  });

  const deepReviewMutation = useMutation<OpportunityFitV2StageResponse, unknown>({
    mutationFn: () => {
      if (!v2Triage) throw new Error('Triage is required');
      return createOpportunityFitV2DeepReview(application!.id, v2Triage.review_id, {
        schema_version: 2,
        resume_id: v2Triage.resume_id ?? resumeID!,
        jd_version_id: v2Triage.jd_version_id!,
        jd_source_label: OPPORTUNITY_FIT_COPY.drawer.jdSourceLabel,
        candidate_assertions: assertions,
        idempotency_key: crypto.randomUUID(),
        parent_triage_stage_id: v2Triage.stage_id,
      });
    },
    onSuccess: (nextReview) => {
      setV2Deep(nextReview);
      setActionError(null);
    },
    onError: (error) => setActionError(getOpportunityFitErrorMessage(error)),
  });

  const canSubmit = Boolean(
    application
      && resumeID
      && jdVersionId
      && !assertionError
      && !createMutation.isPending,
  );

  const submit = () => {
    if (!canSubmit || !resumeID || !jdVersionId || assertionError) return;
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
      setV2Triage(null);
      setV2Deep(null);
      setV2Historical(false);
      setStage('review');
    } catch (error) {
      setActionError(getOpportunityFitErrorMessage(error));
    }
  };

  const openHistoricalV2Review = async (reviewID: number) => {
    if (!application) return;
    try {
      const historical = await getOpportunityFitV2Review(application.id, reviewID);
      const triage = historical.stages.find((item) => item.stage === 'triage') ?? null;
      const deep = historical.stages.find((item) => item.stage === 'deep_review') ?? null;
      setReview(null);
      setV2Triage(triage);
      setV2Deep(deep);
      setV2Historical(true);
      setStage('review');
      setActionError(null);
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
      {reviewHistoryQuery.error ? (
        <Alert
          type="error"
          showIcon
          message={getOpportunityFitErrorMessage(reviewHistoryQuery.error)}
        />
      ) : null}

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
      {stage === 'input' && v2HistoryQuery.data && v2HistoryQuery.data.length > 0 ? (
        <Card size="small" title="岗位评估历史（v2，只读）" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {v2HistoryQuery.data.map((item) => (
              <Space key={`v2-${item.review_id}`} style={{ justifyContent: 'space-between', width: '100%' }}>
                <Typography.Text>评估 #{item.review_id} · {item.stage_count} 个阶段</Typography.Text>
                <Button size="small" onClick={() => void openHistoricalV2Review(item.review_id)}>查看</Button>
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
              rows={9}
              readOnly
              aria-readonly="true"
              placeholder={OPPORTUNITY_FIT_COPY.drawer.jdPlaceholder}
            />
            <Typography.Text type="secondary">
              {currentJdText ? '使用投递当前已确认的岗位资料；如需修改，请先返回 JD 版本入口。' : '当前投递尚未确认岗位资料，请先保存 JD 版本。'}
            </Typography.Text>
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
      ) : v2Triage ? (
        <div>
          <Space wrap>
            <Tag color="blue">v2 岗位评估</Tag>
            <SourceStateTag state="frozen" detail={OPPORTUNITY_FIT_COPY.drawer.sourceFrozen} />
            <Tag>{OPPORTUNITY_FIT_COPY.drawer.humanConfirmation}</Tag>
          </Space>
          <Typography.Title level={4}>Triage</Typography.Title>
          {v2Triage.proposal ? <V2ProposalView proposal={v2Triage.proposal} /> : <Spin />}
          {v2Triage.stage_status === 'ready' && v2Triage.confirmation_token ? (
            <Button
              type="primary"
              onClick={() => confirmV2Mutation.mutate()}
              loading={confirmV2Mutation.isPending}
            >
              确认 Triage
            </Button>
          ) : null}
          {!v2Historical && v2Triage.stage_status === 'confirmed' && !v2Deep ? (
            <Button
              type="primary"
              onClick={() => deepReviewMutation.mutate()}
              loading={deepReviewMutation.isPending}
            >
              开始 Deep Review
            </Button>
          ) : null}
          {v2Deep ? (
            <>
              <Divider />
              <Typography.Title level={4}>Deep Review</Typography.Title>
              {v2Deep.proposal ? <V2ProposalView proposal={v2Deep.proposal} /> : <Spin />}
              <Button
                type="primary"
                onClick={() => onPrepareMaterials?.(
                  v2Deep.resume_id ?? resumeID!,
                  currentJdText || jdText,
                  v2Deep.jd_version_id ?? undefined,
                )}
                disabled={!onPrepareMaterials || !v2Deep.resume_id || !v2Deep.jd_version_id || v2Historical}
              >
                {OPPORTUNITY_FIT_COPY.drawer.prepareMaterials}
              </Button>
            </>
          ) : null}
        </div>
      ) : review ? (
        <div>
          <Space wrap>
            <Tag color={opportunityFitRecommendationColor(review.recommendation)}>
              {opportunityFitRecommendationLabel(review.recommendation)}
            </Tag>
            <SourceStateTag state="frozen" detail={OPPORTUNITY_FIT_COPY.drawer.sourceFrozen} />
            <Tag>{OPPORTUNITY_FIT_COPY.drawer.humanConfirmation}</Tag>
          </Space>
          <Typography.Title level={4}>{OPPORTUNITY_FIT_COPY.drawer.triage}</Typography.Title>
          <Typography.Paragraph>{review.triage.summary.text}</Typography.Paragraph>
          <EvidenceRefs refs={review.triage.summary.evidence_refs} />

          <Typography.Title level={5}>{OPPORTUNITY_FIT_COPY.drawer.hardConstraints}</Typography.Title>
          {review.triage.hard_constraints.map((item) => (
            <ReviewItem
              key={item.id}
              title={`${item.requirement} · ${opportunityFitStatusLabel(item.status)}`}
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
              title={`${opportunityFitGapKindLabel(item.kind)} · ${opportunityFitStatusLabel(item.candidate_status)}`}
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
            <Typography.Text>{OPPORTUNITY_FIT_COPY.evidence.resume}：{review.source.resume.title}</Typography.Text>
            <br />
            <Typography.Text>{OPPORTUNITY_FIT_COPY.evidence.jd}：{review.source.jd.source_label}</Typography.Text>
            <Typography.Paragraph type="secondary">{OPPORTUNITY_FIT_COPY.drawer.jdOriginal}</Typography.Paragraph>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{review.source.jd.text}</Typography.Paragraph>
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
          ) : null}
        </div>
      ) : (
        <Spin />
      )}
    </Drawer>
  );
}
