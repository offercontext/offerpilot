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

interface Props {
  application: Application | null;
  open: boolean;
  onClose: () => void;
  onPrepareMaterials?: (review: OpportunityFitReview, jdText: string) => void;
}

function getErrorMessage(error: unknown): string {
  const responseData = (
    error as { response?: { data?: { error_code?: unknown; error?: unknown } } }
  )?.response?.data;
  if (responseData?.error_code === 'opportunity_fit_unverifiable') {
    return 'AI 输出未通过证据校验，可重试；原简历已保护，未创建草稿。';
  }
  if (typeof responseData?.error === 'string' && responseData.error) return responseData.error;
  if (error instanceof Error && error.message) return error.message;
  return '操作失败，请稍后重试';
}

function evidenceLabel(source: OpportunityFitEvidenceRef['source']): string {
  if (source === 'resume') return '简历';
  if (source === 'user_assertion') return '用户提供，未外部核验';
  return '岗位要求（仅用于分析方向）';
}

function EvidenceRefs({ refs }: { refs: OpportunityFitEvidenceRef[] }) {
  if (refs.length === 0) return <Typography.Text type="secondary">无直接证据引用</Typography.Text>;
  return (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      {refs.map((ref) => (
        <Typography.Text key={`${ref.source}:${ref.path}:${ref.excerpt}`} type="secondary">
          {evidenceLabel(ref.source)} · {ref.path} · “{ref.excerpt}”
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
    ? '最多填写 10 条非空断言。'
    : assertions.some((value) => value.length > 500)
      ? '每条断言最多 500 字。'
      : null;

  const createMutation = useMutation({
    mutationFn: () => createOpportunityFitReview(application!.id, {
      resume_id: resumeID!,
      jd_text: jdText.trim(),
      jd_source_label: '用户粘贴 JD',
      candidate_assertions: assertions,
      idempotency_key: crypto.randomUUID(),
    }),
    onSuccess: (nextReview) => {
      setReview(nextReview);
      setStage('review');
      setActionError(null);
    },
    onError: (error) => setActionError(getErrorMessage(error)),
  });

  const deepReviewMutation = useMutation({
    mutationFn: () => createOpportunityFitDeepReview(application!.id, review!.id),
    onSuccess: (nextReview) => {
      setReview(nextReview);
      setActionError(null);
    },
    onError: (error) => setActionError(getErrorMessage(error)),
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
      setActionError(getErrorMessage(error));
    }
  };

  if (!open) return null;

  return (
    <Drawer
      open={open}
      width={680}
      title="岗位决策漏斗"
      onClose={onClose}
      destroyOnClose
    >
      <Typography.Paragraph type="secondary">
        先判断是否值得投入，再决定是否准备材料。分析只基于本地 Application、选定简历、用户粘贴 JD 和你的补充断言。
      </Typography.Paragraph>
      {actionError ? <Alert type="error" showIcon message={actionError} /> : null}

      {stage === 'input' && reviewHistoryQuery.data && reviewHistoryQuery.data.length > 0 ? (
        <Card size="small" title="历史评估（只读快照）" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {reviewHistoryQuery.data.map((item) => (
              <Space key={item.id} style={{ justifyContent: 'space-between', width: '100%' }}>
                <Typography.Text>
                  {item.recommendation} · {new Date(item.created_at).toLocaleString()}
                </Typography.Text>
                <Button size="small" onClick={() => void openHistoricalReview(item.id)}>
                  查看
                </Button>
              </Space>
            ))}
          </Space>
        </Card>
      ) : null}

      {stage === 'input' ? (
        <Form layout="vertical">
          <Form.Item label="用于审阅的简历" required>
            <Select
              value={resumeID}
              onChange={setResumeID}
              loading={resumesQuery.isFetching}
              placeholder="选择一份简历"
              options={(resumesQuery.data || []).map((resume: Resume) => ({
                value: resume.id,
                label: resume.name || resume.title,
              }))}
            />
          </Form.Item>
          <Form.Item label="用户粘贴的 JD" required>
            <Input.TextArea
              value={jdText}
              onChange={(event) => setJdText(event.target.value)}
              rows={9}
              placeholder="只粘贴岗位要求文本；不会抓取链接。"
            />
          </Form.Item>
          <Form.Item label="本次补充断言（每行一条）">
            <Input.TextArea
              value={assertionsText}
              onChange={(event) => setAssertionsText(event.target.value)}
              rows={5}
              placeholder="例如：我可以在上海办公"
            />
            <Typography.Text type="secondary">最多 10 条，每条最多 500 字。</Typography.Text>
            {assertionError ? <Typography.Text type="danger">{assertionError}</Typography.Text> : null}
          </Form.Item>
          <Alert
            type="info"
            showIcon
            message="人工确认"
            description="AI 只生成带证据引用的分析，不会自动接受、投递或访问外部招聘平台。"
          />
          <Button type="primary" onClick={submit} loading={createMutation.isPending} disabled={!canSubmit}>
            开始 Triage
          </Button>
        </Form>
      ) : review ? (
        <div>
          <Space wrap>
            <Tag color={review.recommendation === 'advance' ? 'green' : review.recommendation === 'decline' ? 'red' : 'gold'}>
              {review.recommendation === 'advance' ? '建议推进' : review.recommendation === 'decline' ? '建议放弃' : '需要澄清'}
            </Tag>
            <Tag>来源已冻结</Tag>
            <Tag>人工确认</Tag>
          </Space>
          <Typography.Title level={4}>Triage</Typography.Title>
          <Typography.Paragraph>{review.triage.summary.text}</Typography.Paragraph>
          <EvidenceRefs refs={review.triage.summary.evidence_refs} />

          <Typography.Title level={5}>岗位约束</Typography.Title>
          {review.triage.hard_constraints.map((item) => (
            <ReviewItem
              key={item.id}
              title={`${item.requirement} · ${item.status}`}
              statement={item.explanation}
              refs={item.evidence_refs}
            />
          ))}
          <Typography.Title level={5}>候选人匹配信号</Typography.Title>
          {review.triage.fit_signals.map((item) => (
            <ReviewItem key={item.id} statement={item.statement} refs={item.evidence_refs} />
          ))}
          <Typography.Title level={5}>差距与待确认问题</Typography.Title>
          {review.triage.gaps.map((item) => (
            <ReviewItem
              key={item.id}
              title={`${item.kind} · ${item.candidate_status}`}
              statement={item.requirement}
              refs={item.evidence_refs}
            />
          ))}
          {review.triage.next_questions.map((question) => (
            <Typography.Paragraph key={question}>？ {question}</Typography.Paragraph>
          ))}
          <Typography.Title level={5}>截止日期</Typography.Title>
          <Typography.Paragraph>
            {review.triage.deadline.status === 'stated' ? review.triage.deadline.text : '未在输入材料中陈述'}
          </Typography.Paragraph>
          <EvidenceRefs refs={review.triage.deadline.evidence_refs} />

          <Divider />
          <Typography.Title level={5}>证据来源</Typography.Title>
          <Card size="small">
            <Typography.Text>简历：{review.source.resume.title}</Typography.Text>
            <br />
            <Typography.Text>JD：{review.source.jd.source_label}（仅决定分析方向）</Typography.Text>
            {review.source.candidate_assertions.length > 0 ? (
              <>
                <Typography.Paragraph strong>用户断言（用户提供，未外部核验）</Typography.Paragraph>
                {review.source.candidate_assertions.map((assertion) => (
                  <Typography.Paragraph key={assertion.index}>· {assertion.text}</Typography.Paragraph>
                ))}
              </>
            ) : null}
          </Card>

          {review.deep_review ? (
            <>
              <Typography.Title level={4}>Deep Fit Review</Typography.Title>
              <Typography.Paragraph>建议路径：{review.deep_review.recommended_path}</Typography.Paragraph>
              {review.deep_review.strengths.map((item) => (
                <ReviewItem key={item.id} statement={item.statement} refs={item.evidence_refs} />
              ))}
              {review.deep_review.gaps_to_address.map((item) => (
                <ReviewItem key={item.id} statement={item.statement} refs={item.evidence_refs} />
              ))}
              {review.deep_review.questions_to_clarify.map((item) => (
                <ReviewItem key={item.id} statement={item.statement} refs={item.evidence_refs} />
              ))}
              <Typography.Title level={5}>下一步行动</Typography.Title>
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
                去准备材料
              </Button>
            </>
          ) : (
            <Button
              type="primary"
              onClick={() => deepReviewMutation.mutate()}
              loading={deepReviewMutation.isPending}
            >
              开始 Deep Fit Review
            </Button>
          )}
        </div>
      ) : (
        <Spin />
      )}
    </Drawer>
  );
}
