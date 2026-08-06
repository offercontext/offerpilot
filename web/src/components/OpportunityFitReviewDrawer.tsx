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
import { getApplicationJdVersion } from '@/services/applicationJdVersions';
import type { Application } from '@/types/application';
import type { Resume } from '@/types/resume';
import type {
  OpportunityFitEvidenceRef,
  OpportunityFitReview,
  OpportunityFitV2EvidenceRef,
  OpportunityFitV2Proposal,
  OpportunityFitV2StageResponse,
  OpportunityFitV2Draft,
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
  draft?: OpportunityFitV2Draft;
  onDraftChange?: (patch: Partial<OpportunityFitV2Draft> | null) => void;
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
  draft,
  onDraftChange,
}: Props) {
  const [stage, setStage] = useState<'input' | 'review'>('input');
  const [resumeID, setResumeID] = useState<number | undefined>(draft?.resumeId);
  const [jdText, setJdText] = useState(draft?.jdText || currentJdText);
  const [assertionsText, setAssertionsText] = useState(draft?.assertionsText ?? '');
  const [review, setReview] = useState<OpportunityFitReview | null>(null);
  const [v2Triage, setV2Triage] = useState<OpportunityFitV2StageResponse | null>(draft?.triage ?? null);
  const [v2Deep, setV2Deep] = useState<OpportunityFitV2StageResponse | null>(draft?.deep ?? null);
  const [v2Historical, setV2Historical] = useState(false);
  const [actionError, setActionError] = useState<string | null>(draft?.error ?? null);

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

  const frozenJdQuery = useQuery({
    queryKey: ['application-jd-version', application?.id, v2Deep?.jd_version_id],
    queryFn: () => getApplicationJdVersion(application!.id, v2Deep!.jd_version_id!),
    enabled: open && Boolean(application && v2Deep?.jd_version_id),
  });

  useEffect(() => {
    if (!open) return;
    setStage(draft?.triage || draft?.deep ? 'review' : 'input');
    setResumeID(draft?.resumeId);
    setJdText(draft?.jdText || currentJdText);
    setAssertionsText(draft?.assertionsText ?? '');
    setReview(null);
    setV2Triage(draft?.triage ?? null);
    setV2Deep(draft?.deep ?? null);
    setV2Historical(Boolean(draft?.historical));
    setActionError(draft?.error ?? null);
  // The AppShell draft is the source of truth across unmount/remount. Do not
  // reset it on ordinary parent renders or current-JD query refreshes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [application?.id, open]);

  useEffect(() => {
    if (!open || stage !== 'input' || v2Triage || v2Deep || v2Historical) return;
    const hasActiveAttempt = Boolean(draft?.triageKey || draft?.deepKey);
    if (!hasActiveAttempt && currentJdText && draft?.jdVersionId !== jdVersionId) {
      setJdText(currentJdText);
      onDraftChange?.({ jdText: currentJdText, jdVersionId: jdVersionId ?? undefined });
    }
  }, [currentJdText, draft?.deepKey, draft?.jdVersionId, draft?.triageKey, jdVersionId, onDraftChange, open, stage, v2Deep, v2Historical, v2Triage]);

  const assertions = useMemo(
    () => assertionsText.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
    [assertionsText],
  );
  const assertionError = assertions.length > 10
    ? OPPORTUNITY_FIT_COPY.drawer.assertionsTooMany
    : assertions.some((value) => value.length > 500)
      ? OPPORTUNITY_FIT_COPY.drawer.assertionsTooLong
      : null;

  const errorCode = (error: unknown): string | undefined => {
    if (!error || typeof error !== 'object') return undefined;
    const candidate = error as { response?: { data?: { error_code?: unknown } }; code?: unknown };
    const responseCode = candidate.response?.data?.error_code;
    return typeof responseCode === 'string'
      ? responseCode
      : typeof candidate.code === 'string' ? candidate.code : undefined;
  };

  const isProviderUnknown = (error: unknown): boolean => {
    const code = errorCode(error);
    if (code === 'opportunity_fit_unverifiable') return false;
    if (code === 'opportunity_fit_provider_error') return true;
    if (!error || typeof error !== 'object') return true;
    const response = (error as { response?: unknown }).response;
    if (!response || typeof response !== 'object') return true;
    const status = (response as { status?: unknown }).status;
    return typeof status === 'number' && status >= 500;
  };

  const unknownResultCopy = '操作结果待确认，请使用原尝试重试。';

  const recoverConfirmedTriage = async (): Promise<boolean> => {
    if (!application || !v2Triage) return false;
    try {
      const session = await getOpportunityFitV2Review(application.id, v2Triage.review_id);
      const current = session.stages.find((item) => (
        item.stage === 'triage' && item.stage_id === v2Triage.stage_id
      )) ?? session.stages.find((item) => item.stage === 'triage');
      if (current?.stage_status !== 'confirmed') return false;
      setV2Triage(current);
      setStage('review');
      setActionError(null);
      onDraftChange?.({ triage: current, resultUnknown: false, error: null });
      return true;
    } catch {
      return false;
    }
  };

  const isConfirmationConsumed = (error: unknown): boolean => (
    errorCode(error) === 'opportunity_fit_triage_confirmation_consumed'
  );

  const createMutation = useMutation({
    mutationFn: (input: Parameters<typeof createOpportunityFitV2Triage>[1]) => (
      createOpportunityFitV2Triage(application!.id, input)
    ),
    onSuccess: (nextReview) => {
      setV2Triage(nextReview);
      setV2Deep(null);
      setStage('review');
      setActionError(null);
      onDraftChange?.({
        triage: nextReview,
        deep: null,
        triageKey: nextReview.idempotency_key,
        resultUnknown: ['generating', 'provider_unknown'].includes(nextReview.stage_status),
        error: ['generating', 'provider_unknown'].includes(nextReview.stage_status) ? unknownResultCopy : null,
      });
    },
    onError: (error, input) => {
      const unknown = isProviderUnknown(error);
      setActionError(unknown ? unknownResultCopy : getOpportunityFitErrorMessage(error));
      onDraftChange?.({
        resultUnknown: unknown,
        error: unknown ? unknownResultCopy : getOpportunityFitErrorMessage(error),
        triageKey: unknown ? input.idempotency_key : null,
      });
    },
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
    onSuccess: (nextReview) => {
      setV2Triage(nextReview);
      onDraftChange?.({ triage: nextReview, resultUnknown: false, error: null });
    },
    onError: async (error) => {
      if (isConfirmationConsumed(error) || isProviderUnknown(error)) {
        if (await recoverConfirmedTriage()) return;
        setActionError(unknownResultCopy);
        onDraftChange?.({ resultUnknown: true, error: unknownResultCopy });
        return;
      }
      setActionError(getOpportunityFitErrorMessage(error));
    },
  });

  const deepReviewMutation = useMutation<
    OpportunityFitV2StageResponse,
    unknown,
    Parameters<typeof createOpportunityFitV2DeepReview>[2]
  >({
    mutationFn: (input: Parameters<typeof createOpportunityFitV2DeepReview>[2]) => {
      if (!v2Triage) throw new Error('Triage is required');
      return createOpportunityFitV2DeepReview(application!.id, v2Triage.review_id, input);
    },
    onSuccess: (nextReview) => {
      setV2Deep(nextReview);
      setActionError(null);
      onDraftChange?.({
        deep: nextReview,
        deepKey: nextReview.idempotency_key,
        resultUnknown: ['generating', 'provider_unknown'].includes(nextReview.stage_status),
        error: ['generating', 'provider_unknown'].includes(nextReview.stage_status) ? unknownResultCopy : null,
      });
    },
    onError: (error, input) => {
      const unknown = isProviderUnknown(error);
      setActionError(unknown ? unknownResultCopy : getOpportunityFitErrorMessage(error));
      onDraftChange?.({
        resultUnknown: unknown,
        error: unknown ? unknownResultCopy : getOpportunityFitErrorMessage(error),
        deepKey: unknown ? input.idempotency_key : null,
      });
    },
  });

  const canSubmit = Boolean(
    application
      && (draft?.triageKey ? draft.resumeId && draft.jdVersionId : resumeID && jdVersionId)
      && !assertionError
      && !createMutation.isPending,
  );

  const buildTriageInput = () => {
    const frozen = Boolean(draft?.triageKey);
    const selectedResumeID = frozen ? draft?.resumeId : resumeID;
    const selectedJdVersionId = frozen ? draft?.jdVersionId : jdVersionId;
    if (!selectedResumeID || !selectedJdVersionId) return null;
    return {
      schema_version: 2 as const,
      resume_id: selectedResumeID,
      jd_version_id: selectedJdVersionId,
      jd_source_label: OPPORTUNITY_FIT_COPY.drawer.jdSourceLabel,
      candidate_assertions: frozen
        ? (draft?.assertionsText ?? '').split(/\r?\n/).map((value) => value.trim()).filter(Boolean)
        : assertions,
      idempotency_key: draft?.triageKey ?? crypto.randomUUID(),
    };
  };

  const submit = () => {
    if (!canSubmit || assertionError) return;
    const input = buildTriageInput();
    if (!input) return;
    onDraftChange?.({
      resumeId: input.resume_id,
      jdText,
      jdVersionId: input.jd_version_id,
      assertionsText,
      triageKey: input.idempotency_key,
      resultUnknown: false,
      error: null,
    });
    createMutation.mutate(input);
  };

  const submitDeepReview = () => {
    if (!v2Triage || v2Triage.stage_status !== 'confirmed' || !v2Triage.jd_version_id || !resumeID) return;
    const input = {
      schema_version: 2 as const,
      resume_id: draft?.deepKey ? (draft.resumeId ?? v2Triage.resume_id ?? resumeID) : (v2Triage.resume_id ?? resumeID),
      jd_version_id: v2Triage.jd_version_id,
      jd_source_label: OPPORTUNITY_FIT_COPY.drawer.jdSourceLabel,
      candidate_assertions: draft?.deepKey
        ? (draft.assertionsText ?? '').split(/\r?\n/).map((value) => value.trim()).filter(Boolean)
        : assertions,
      idempotency_key: draft?.deepKey ?? crypto.randomUUID(),
      parent_triage_stage_id: v2Triage.stage_id,
    };
    // Persist the key before the request leaves the page. If the response is
    // lost during unmount, AppShell can still replay this exact attempt.
    onDraftChange?.({
      resumeId: input.resume_id,
      jdVersionId: input.jd_version_id,
      assertionsText,
      deepKey: input.idempotency_key,
      resultUnknown: false,
      error: null,
    });
    deepReviewMutation.mutate(input);
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

  const resetV2Review = () => {
    onDraftChange?.(null);
    setStage('input');
    setResumeID(undefined);
    setJdText(currentJdText);
    setAssertionsText('');
    setReview(null);
    setV2Triage(null);
    setV2Deep(null);
    setV2Historical(false);
    setActionError(null);
  };

  const canStartNewV2Review = Boolean(
    v2Historical
      || ['ready', 'confirmed', 'source_conflict'].includes(v2Triage?.stage_status ?? '')
      || ['ready', 'confirmed', 'source_conflict'].includes(v2Deep?.stage_status ?? ''),
  );
  const v2HasSourceConflict = v2Triage?.stage_status === 'source_conflict'
    || v2Deep?.stage_status === 'source_conflict';

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
              disabled={Boolean(draft?.resultUnknown)}
              onChange={(value) => {
                setResumeID(value as number);
                onDraftChange?.({ resumeId: value as number });
              }}
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
              disabled={Boolean(draft?.resultUnknown)}
              onChange={(event) => {
                setAssertionsText(event.target.value);
                onDraftChange?.({ assertionsText: event.target.value });
              }}
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
            {draft?.triageKey ? '使用原尝试重试' : OPPORTUNITY_FIT_COPY.drawer.startTriage}
          </Button>
        </Form>
      ) : v2Triage ? (
        <div>
          <Space wrap>
            <Tag color="blue">v2 岗位评估</Tag>
            <SourceStateTag
              state={v2HasSourceConflict ? 'changed' : 'frozen'}
              detail={v2HasSourceConflict ? '岗位资料版本已变化' : OPPORTUNITY_FIT_COPY.drawer.sourceFrozen}
            />
            <Tag>{OPPORTUNITY_FIT_COPY.drawer.humanConfirmation}</Tag>
          </Space>
          <Typography.Title level={4}>Triage</Typography.Title>
          {v2Triage.stage_status === 'source_conflict' ? (
            <Alert type="warning" showIcon message="岗位资料版本已变化，当前评估仅供只读查看。" />
          ) : v2Triage.proposal ? <V2ProposalView proposal={v2Triage.proposal} /> : <Spin />}
          {['generating', 'provider_unknown'].includes(v2Triage.stage_status) ? (
            <Button type="primary" onClick={submit} loading={createMutation.isPending} disabled={!canSubmit}>
              使用原尝试重试
            </Button>
          ) : null}
          {v2Triage.stage_status === 'ready' && v2Triage.confirmation_token ? (
            <Button
              type="primary"
              onClick={() => confirmV2Mutation.mutate()}
              loading={confirmV2Mutation.isPending}
            >
              {draft?.resultUnknown ? '使用原尝试重试' : '确认 Triage'}
            </Button>
          ) : null}
          {!v2Historical && v2Triage.stage_status === 'confirmed' && !v2Deep ? (
            <Button
              type="primary"
              onClick={submitDeepReview}
              loading={deepReviewMutation.isPending}
            >
              {draft?.deepKey ? '使用原尝试重试' : '开始 Deep Review'}
            </Button>
          ) : null}
          {v2Deep ? (
            <>
              <Divider />
              <Typography.Title level={4}>Deep Review</Typography.Title>
              {v2Deep.stage_status === 'source_conflict' ? (
                <Alert type="warning" showIcon message="岗位资料版本已变化，当前评估仅供只读查看。" />
              ) : v2Deep.proposal ? <V2ProposalView proposal={v2Deep.proposal} /> : <Spin />}
              {['generating', 'provider_unknown'].includes(v2Deep.stage_status) ? (
                <Button type="primary" onClick={submitDeepReview} loading={deepReviewMutation.isPending}>
                  使用原尝试重试
                </Button>
              ) : null}
              {v2Deep.jd_version_id !== jdVersionId ? (
                <Alert type="warning" showIcon message="岗位资料版本已变化，当前结果仅供只读查看。请重新开始评估。" />
              ) : null}
              <Button
                type="primary"
                onClick={() => onPrepareMaterials?.(
                  v2Deep.resume_id ?? resumeID!,
                  (frozenJdQuery.data as { jd_text?: string } | undefined)?.jd_text ?? '',
                  v2Deep.jd_version_id ?? undefined,
                )}
                disabled={
                  !onPrepareMaterials
                  || !v2Deep.resume_id
                  || !v2Deep.jd_version_id
                  || v2Historical
                  || !frozenJdQuery.data
                  || v2Deep.jd_version_id !== jdVersionId
                }
              >
                {OPPORTUNITY_FIT_COPY.drawer.prepareMaterials}
              </Button>
            </>
          ) : null}
          {canStartNewV2Review && !draft?.resultUnknown ? (
            <Button onClick={resetV2Review}>重新开始岗位评估</Button>
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
            </>
          ) : null}
        </div>
      ) : (
        <Spin />
      )}
    </Drawer>
  );
}
