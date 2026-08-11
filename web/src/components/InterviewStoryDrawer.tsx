import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Checkbox, Divider, Drawer, Empty, Input, List, Space, Spin, Tag, Typography, message } from 'antd';
import {
  confirmInterviewStoryProposal,
  createInterviewStory,
  createInterviewStoryVersion,
  createInterviewStoryProposal,
  InterviewStoryError,
  listInterviewStorySourceCandidates,
} from '@/services/interviewStories';
import type {
  InterviewStoryClientEvidenceLink,
  InterviewStoryContent,
  InterviewStoryEvidenceLink,
  InterviewStoryEditableContent,
  InterviewStoryProposalAttempt,
  InterviewStoryProposalInput,
  InterviewStorySourceCandidates,
  InterviewStorySourceSelection,
} from '@/types/interviewStory';

const { Text, Title } = Typography;

type EntryPoint = 'ui' | 'pilot';

export interface InterviewStoryDraft {
  entrypoint: EntryPoint;
  reviewNoteId?: number;
  targetStoryId: number | null;
  expectedCurrentVersionId: number | null;
  expectedStoryRevision: number | null;
  selections: InterviewStorySourceSelection[];
  assertions: string[];
  manualEvidenceBindings: Record<string, string>;
  idempotencyKey: string;
  attemptId: number | null;
  proposal: InterviewStoryProposalAttempt['proposal'] | null;
  editedContent: InterviewStoryEditableContent | null;
  manualContent: InterviewStoryEditableContent;
  manualSavePayload: { content: InterviewStoryEditableContent; evidenceLinks: InterviewStoryClientEvidenceLink[] } | null;
  proposalInput: InterviewStoryProposalInput | null;
  resultUnknown: boolean;
  pendingOperation: 'generate' | 'confirm' | 'manual' | null;
  confirmationToken: string | null;
  error: string | null;
}

interface Props {
  open: boolean;
  draft: InterviewStoryDraft;
  onDraftChange: (draft: InterviewStoryDraft | null) => void;
  onClose: () => void;
}

const EMPTY_MANUAL_CONTENT: InterviewStoryEditableContent = {
  title: '',
  blocks: [
    { kind: 'situation', text: '', fact_mode: 'evidence_backed' },
    { kind: 'task', text: '', fact_mode: 'evidence_backed' },
    { kind: 'action', text: '', fact_mode: 'evidence_backed' },
    { kind: 'result', text: '', fact_mode: 'evidence_backed' },
    { kind: 'reflection', text: '', fact_mode: 'user_view' },
  ],
  capability_labels: [],
  applicable_questions: [],
  fact_gap_codes: [],
};

function key(prefix: string): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function createInterviewStoryDraft(
  entrypoint: EntryPoint,
  reviewNoteId?: number,
  revision?: { targetStoryId?: number; expectedCurrentVersionId?: number; expectedStoryRevision?: number },
): InterviewStoryDraft {
  return {
    entrypoint,
    reviewNoteId,
    targetStoryId: revision?.targetStoryId ?? null,
    expectedCurrentVersionId: revision?.expectedCurrentVersionId ?? null,
    expectedStoryRevision: revision?.expectedStoryRevision ?? null,
    selections: [],
    assertions: [],
    manualEvidenceBindings: {},
    idempotencyKey: key('story'),
    attemptId: null,
    proposal: null,
    editedContent: null,
    manualContent: EMPTY_MANUAL_CONTENT,
    manualSavePayload: null,
    proposalInput: null,
    resultUnknown: false,
    pendingOperation: null,
    confirmationToken: null,
    error: null,
  };
}

function safeMessage(error: unknown): string {
  if (error instanceof InterviewStoryError) {
    if (error.code === 'story_unverifiable') return 'AI 草稿未通过证据校验，请重新开始。';
    if (error.code === 'story_provider_error') return 'AI 服务结果待确认，请使用原尝试重试。';
    if (error.status === 404) return '选中的来源已不可用，请重新选择。';
    if (error.status === 409) return '故事或来源已变化，请重新确认后继续。';
    if (error.status === 422) return '所选内容无法作为故事证据，请调整后重试。';
  }
  return '操作结果待确认，请使用原尝试重试。';
}

function editableContent(content: InterviewStoryContent): InterviewStoryEditableContent {
  return {
    title: content.title.text,
    blocks: content.blocks.map(({ kind, text, fact_mode }) => ({ kind, text, fact_mode })),
    capability_labels: content.capability_labels.map((item) => item.text),
    applicable_questions: content.applicable_questions.map((item) => item.text),
    fact_gap_codes: content.fact_gap_codes,
  };
}

function normalizedManualContent(content: InterviewStoryEditableContent): InterviewStoryEditableContent {
  const blocks = content.blocks.filter((block) => block.text.trim());
  return {
    title: content.title,
    blocks,
    capability_labels: content.capability_labels.filter((value) => value.trim()),
    applicable_questions: content.applicable_questions.filter((value) => value.trim()),
    fact_gap_codes: blocks.some((block) => block.kind === 'result') ? [] : ['missing_result'],
  };
}

type ManualEvidenceTarget = Pick<InterviewStoryClientEvidenceLink, 'target_kind' | 'target_id'> & { label: string };
type ManualEvidenceSource = { key: string; label: string; link: Omit<InterviewStoryClientEvidenceLink, 'target_kind' | 'target_id'> };

function manualEvidenceKey(target: Pick<ManualEvidenceTarget, 'target_kind' | 'target_id'>): string {
  return `${target.target_kind}:${target.target_id}`;
}

function manualEvidenceTargets(content: InterviewStoryEditableContent): ManualEvidenceTarget[] {
  const targets: ManualEvidenceTarget[] = [];
  if (content.title.trim()) targets.push({ target_kind: 'title', target_id: 'title', label: '故事标题' });
  const counts: Record<string, number> = {};
  for (const block of content.blocks) {
    counts[block.kind] = (counts[block.kind] ?? 0) + 1;
    if (!block.text.trim()) continue;
    const blockName = ({ situation: '情境', task: '任务', action: '行动', result: '结果', reflection: '复盘' } as const)[block.kind];
    targets.push({
      target_kind: 'block',
      target_id: `${block.kind}_${String(counts[block.kind]).padStart(3, '0')}`,
      label: `故事${blockName}`,
    });
  }
  content.capability_labels.forEach((value, index) => {
    if (value.trim()) targets.push({ target_kind: 'capability_label', target_id: `capability_${String(index + 1).padStart(3, '0')}`, label: `能力标签 ${index + 1}` });
  });
  content.applicable_questions.forEach((value, index) => {
    if (value.trim()) targets.push({ target_kind: 'applicable_question', target_id: `question_${String(index + 1).padStart(3, '0')}`, label: `适用问题 ${index + 1}` });
  });
  return targets;
}

function clientEvidence(links: InterviewStoryEvidenceLink[]): InterviewStoryClientEvidenceLink[] {
  return links.map((link) => ({
    target_kind: link.target_kind,
    target_id: link.target_id,
    source_kind: link.source_kind,
    source_id: link.source_stable_id,
    source_path: link.source_path,
    excerpt: link.excerpt,
    text_location: link.text_location,
  }));
}

function isUnknownResult(error: unknown): boolean {
  if (!(error instanceof InterviewStoryError)) return true;
  if (error.code === 'story_provider_error' || error.status === 0) return true;
  // Stable contract/source failures intentionally use 5xx/409 response codes
  // but have a machine-readable code and must start a fresh user attempt.
  return error.code === null && error.status >= 500;
}

function resetAfterDefiniteFailure(draft: InterviewStoryDraft, error: string | null): InterviewStoryDraft {
  return {
    ...createInterviewStoryDraft(draft.entrypoint, draft.reviewNoteId, {
      targetStoryId: draft.targetStoryId ?? undefined,
      expectedCurrentVersionId: draft.expectedCurrentVersionId ?? undefined,
      expectedStoryRevision: draft.expectedStoryRevision ?? undefined,
    }),
    selections: draft.selections,
    assertions: draft.assertions,
    error,
  };
}

function resetAfterSourceConflict(draft: InterviewStoryDraft, error: string): InterviewStoryDraft {
  return {
    ...createInterviewStoryDraft(draft.entrypoint, draft.reviewNoteId, {
      targetStoryId: draft.targetStoryId ?? undefined,
      expectedCurrentVersionId: draft.expectedCurrentVersionId ?? undefined,
      expectedStoryRevision: draft.expectedStoryRevision ?? undefined,
    }),
    assertions: draft.assertions,
    manualContent: draft.editedContent ?? draft.manualContent,
    error,
  };
}

export default function InterviewStoryDrawer({ open, draft, onDraftChange, onClose }: Props) {
  const [candidates, setCandidates] = useState<InterviewStorySourceCandidates | null>(null);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [previewConfirmed, setPreviewConfirmed] = useState(false);
  const [assertion, setAssertion] = useState('');
  const [busy, setBusy] = useState(false);
  const [authoringMode, setAuthoringMode] = useState<'proposal' | 'manual'>('proposal');

  useEffect(() => {
    // AppShell keeps independent UI/Pilot drafts alive for an unknown-result
    // retry.  A different draft must never reuse the previous picker cache or
    // confirmation choice.
    setCandidates(null);
    setPickerOpen(false);
    setShowPreview(false);
    setPreviewConfirmed(false);
    setAuthoringMode('proposal');
  }, [draft.entrypoint, draft.targetStoryId, draft.reviewNoteId]);

  useEffect(() => {
    if (!open || !pickerOpen || candidates) return;
    setCandidatesLoading(true);
    void listInterviewStorySourceCandidates(draft.reviewNoteId)
      .then(setCandidates)
      .catch(() => setCandidates({ resumes: [], interview_notes: [], mock_turns: [] }))
      .finally(() => setCandidatesLoading(false));
  }, [open, pickerOpen, candidates, draft.reviewNoteId]);

  const sourceSelected = draft.selections.length > 0 || draft.assertions.some((item) => item.trim());
  const frozen = draft.resultUnknown || busy;
  const normalProposal = draft.proposal?.proposal_status === 'normal' ? draft.proposal : null;
  const manualContent = useMemo(() => normalizedManualContent(draft.manualContent), [draft.manualContent]);
  const manualTargets = useMemo(() => manualEvidenceTargets(manualContent), [manualContent]);
  const manualEvidenceSources = useMemo<ManualEvidenceSource[]>(() => {
    const sources: ManualEvidenceSource[] = [];
    for (const selection of draft.selections) {
      const leaves = selection.source_kind === 'resume_version'
        ? candidates?.resumes.find((item) => item.id === selection.source_id)?.leaves
        : selection.source_kind === 'interview_note'
          ? candidates?.interview_notes.find((item) => item.id === selection.source_id)?.leaves
          : candidates?.mock_turns.find((item) => item.attempt_id === selection.source_id)?.leaves;
      const preview = leaves?.find((item) => item.path === selection.path)?.preview;
      if (!preview) continue;
      sources.push({
        key: `selection:${selection.source_kind}:${selection.source_id}:${selection.path}`,
        label: `${selection.source_kind} · ${selection.path}`,
        link: {
          source_kind: selection.source_kind,
          source_id: selection.source_id,
          source_path: selection.path,
          excerpt: preview,
        },
      });
    }
    draft.assertions.forEach((statement, index) => {
      if (!statement.trim()) return;
      sources.push({
        key: `assertion:${index + 1}`,
        label: `用户明确陈述 ${index + 1}`,
        link: {
          source_kind: 'user_assertion',
          source_id: `assertion_${String(index + 1).padStart(3, '0')}`,
          source_path: '/statement',
          excerpt: statement,
        },
      });
    });
    return sources;
  }, [candidates, draft.assertions, draft.selections]);

  const update = (changes: Partial<InterviewStoryDraft>) => onDraftChange({ ...draft, ...changes });

  const discardChangedInput = (changes: Partial<InterviewStoryDraft>) => update({
    ...changes,
    // Changed sources or assertions produce a different frozen input. Never
    // reuse a key that may already name an earlier Attempt or manual save.
    idempotencyKey: key('story'),
    proposal: null,
    editedContent: null,
    manualSavePayload: null,
    manualEvidenceBindings: {},
    proposalInput: null,
    attemptId: null,
    resultUnknown: false,
    pendingOperation: null,
    confirmationToken: null,
    error: null,
  });

  const toggleSource = (selection: InterviewStorySourceSelection) => {
    if (frozen) return;
    const exists = draft.selections.some((item) => item.source_kind === selection.source_kind && item.source_id === selection.source_id && item.path === selection.path);
    discardChangedInput({
      selections: exists
        ? draft.selections.filter((item) => !(item.source_kind === selection.source_kind && item.source_id === selection.source_id && item.path === selection.path))
        : [...draft.selections, selection],
    });
    setShowPreview(false);
  };

  const addAssertion = () => {
    const value = assertion.trim();
    if (!value || frozen) return;
    discardChangedInput({ assertions: [...draft.assertions, value] });
    setAssertion('');
    setShowPreview(false);
  };

  const restartAfterSafeEmpty = () => {
    if (frozen) return;
    onDraftChange(resetAfterDefiniteFailure(draft, null));
    setShowPreview(false);
    setPreviewConfirmed(false);
  };

  const saveManualStory = async () => {
    const saved = draft.manualSavePayload;
    const content = saved?.content ?? manualContent;
    if (!saved && (!sourceSelected || !content.title.trim() || !content.blocks.some((block) => block.text.trim()))) {
      message.error('请先选择原始来源，并填写标题和至少一个故事区块。');
      return;
    }
    if (!saved && content.blocks.some((block) => block.kind === 'reflection') && !draft.assertions.some((item) => item.trim())) {
      message.error('手动复盘需要一条你明确确认的原始陈述作为来源。');
      return;
    }
    const evidenceLinks: InterviewStoryClientEvidenceLink[] = saved?.evidenceLinks ?? (() => {
      const sourceByKey = new Map(manualEvidenceSources.map((source) => [source.key, source]));
      const links = manualTargets.map((target) => {
        const binding = draft.manualEvidenceBindings[manualEvidenceKey(target)];
        const source = binding ? sourceByKey.get(binding) : undefined;
        return source ? { target_kind: target.target_kind, target_id: target.target_id, ...source.link } : null;
      });
      if (links.some((link) => link === null)) {
        message.error('请为每个已填写的故事目标明确选择原始证据。');
        return [];
      }
      return links as InterviewStoryClientEvidenceLink[];
    })();
    if (!saved && evidenceLinks.length !== manualTargets.length) return;
    const requestDraft = saved
      ? draft
      : { ...draft, manualSavePayload: { content, evidenceLinks } };
    if (!saved) onDraftChange(requestDraft);
    setBusy(true);
    try {
      if (draft.targetStoryId) {
        await createInterviewStoryVersion(draft.targetStoryId, {
          content,
          evidence_links: evidenceLinks,
          selections: draft.selections,
          assertions: draft.assertions,
          expected_current_version_id: draft.expectedCurrentVersionId,
          expected_story_revision: draft.expectedStoryRevision ?? 0,
          idempotency_key: draft.idempotencyKey,
        });
      } else {
        await createInterviewStory({
          content,
          evidence_links: evidenceLinks,
          selections: draft.selections,
          assertions: draft.assertions,
          expected_current_version_id: null,
          idempotency_key: draft.idempotencyKey,
        });
      }
      message.success('故事版本已保存。');
      onDraftChange(null);
      onClose();
    } catch (error) {
      const safe = safeMessage(error);
      if (isUnknownResult(error)) {
        onDraftChange({ ...requestDraft, resultUnknown: true, pendingOperation: 'manual', error: safe });
      } else {
        onDraftChange(resetAfterDefiniteFailure(requestDraft, safe));
      }
      message.error(safe);
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    const saved = draft.proposalInput;
    if (!saved && (!sourceSelected || !previewConfirmed)) return;
    const input = saved ?? {
      target_story_id: draft.targetStoryId,
      expected_current_version_id: draft.expectedCurrentVersionId,
      expected_story_revision: draft.expectedStoryRevision,
      selections: draft.selections,
      assertions: draft.assertions,
      idempotency_key: draft.idempotencyKey,
      ...(draft.reviewNoteId ? { entry_context: { review_note_id: draft.reviewNoteId } } : {}),
    };
    const requestDraft = saved ? draft : { ...draft, proposalInput: input };
    if (!saved) onDraftChange(requestDraft);
    setBusy(true);
    try {
      const response = await createInterviewStoryProposal(input, draft.entrypoint);
      if (!('proposal' in response) || response.attempt_status === 'generating' || response.attempt_status === 'provider_unknown') {
        onDraftChange({ ...requestDraft, attemptId: response.id, resultUnknown: true, pendingOperation: 'generate', error: 'AI 结果待确认，请使用原尝试重试。' });
        return;
      }
      onDraftChange({
        ...requestDraft,
        attemptId: response.id,
        proposal: response.proposal ?? null,
        editedContent: response.proposal?.proposal_status === 'normal' ? editableContent(response.proposal.content) : null,
        proposalInput: null,
        resultUnknown: false,
        pendingOperation: null,
        error: null,
      });
    } catch (error) {
      const safe = safeMessage(error);
      if (isUnknownResult(error)) {
        const attemptId = error instanceof InterviewStoryError && error.attemptId !== null
          ? error.attemptId
          : requestDraft.attemptId;
        onDraftChange({ ...requestDraft, attemptId, resultUnknown: true, pendingOperation: 'generate', error: safe });
      } else {
        onDraftChange(resetAfterDefiniteFailure(requestDraft, safe));
      }
      message.error(safe);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!draft.proposal || draft.proposal.proposal_status !== 'normal' || !draft.attemptId) return;
    setBusy(true);
    const token = draft.confirmationToken ?? key('story-confirm');
    try {
      await confirmInterviewStoryProposal(draft.attemptId, {
        confirmation_token: token,
        content: draft.editedContent ?? editableContent(draft.proposal.content),
        evidence_links: clientEvidence(draft.proposal.evidence_links),
        expected_current_version_id: draft.expectedCurrentVersionId,
        expected_story_revision: draft.expectedStoryRevision,
      });
      message.success('故事版本已确认保存。');
      onDraftChange(null);
      onClose();
    } catch (error) {
      const safe = safeMessage(error);
      if (isUnknownResult(error)) {
        update({ confirmationToken: token, resultUnknown: true, pendingOperation: 'confirm', error: safe });
      } else if (error instanceof InterviewStoryError && error.code === 'story_source_conflict') {
        onDraftChange(resetAfterSourceConflict(draft, safe));
      } else {
        onDraftChange(resetAfterDefiniteFailure(draft, safe));
      }
      message.error(safe);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} width={720} destroyOnClose={false} onClose={onClose} title={draft.entrypoint === 'pilot' ? 'Pilot · 整理面试故事' : '整理面试故事'}>
      <Alert
        type="info"
        showIcon
        message="先选择原始证据，再确认发送给 AI"
        description="不会自动选择来源，不会写入知识库；每一条保存内容都需要原始证据或你的明确陈述。"
        style={{ marginBottom: 16 }}
      />
      {draft.error ? <Alert type="warning" showIcon message={draft.error} action={draft.resultUnknown ? <Button size="small" onClick={() => void (draft.pendingOperation === 'confirm' ? confirm() : draft.pendingOperation === 'manual' ? saveManualStory() : generate())}>使用原尝试重试</Button> : undefined} style={{ marginBottom: 16 }} /> : null}
      <Title level={5}>选择原始来源</Title>
      {!pickerOpen ? <Button data-story-audit={`${draft.entrypoint}-source-picker`} disabled={frozen} onClick={() => setPickerOpen(true)}>打开来源选择器</Button> : null}
      {candidatesLoading ? <Spin aria-label="正在加载可选原始来源" /> : null}
      {pickerOpen && !candidatesLoading && candidates ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {candidates.resumes.length > 0 ? <List
            size="small"
            header="已保存简历中的原文叶子"
            dataSource={candidates.resumes}
            renderItem={(resume) => <List.Item><Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text strong>{resume.label}</Text>
              {resume.leaves.map((leaf) => {
                const selection = { source_kind: 'resume_version' as const, source_id: resume.id, path: leaf.path };
                const checked = draft.selections.some((item) => item.source_kind === selection.source_kind && item.source_id === selection.source_id && item.path === selection.path);
                return <Checkbox key={leaf.path} disabled={frozen} checked={checked} onChange={() => toggleSource(selection)}>{leaf.path}：{leaf.preview}</Checkbox>;
              })}
            </Space></List.Item>}
          /> : null}
          {candidates.interview_notes.length > 0 ? <List
            size="small"
            header="已保存面试复盘的原文"
            dataSource={candidates.interview_notes}
            renderItem={(note) => <List.Item><Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text strong>{note.label || `复盘 #${note.id}`}</Text>
              {note.leaves.map((leaf) => {
                const selection = { source_kind: 'interview_note' as const, source_id: note.id, path: leaf.path };
                const checked = draft.selections.some((item) => item.source_kind === selection.source_kind && item.source_id === selection.source_id && item.path === selection.path);
                return <Checkbox key={leaf.path} disabled={frozen} checked={checked} onChange={() => toggleSource(selection)}>{leaf.path}：{leaf.preview}</Checkbox>;
              })}
            </Space></List.Item>}
          /> : null}
          {candidates.mock_turns.length > 0 ? <List
            size="small"
            header="已完成模拟面试的题目与回答"
            dataSource={candidates.mock_turns}
            renderItem={(turn) => <List.Item><Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text strong>{turn.label}</Text>
              {turn.leaves.map((leaf) => {
                const selection = { source_kind: 'mock_turn' as const, source_id: turn.attempt_id, path: leaf.path };
                const checked = draft.selections.some((item) => item.source_kind === selection.source_kind && item.source_id === selection.source_id && item.path === selection.path);
                return <Checkbox key={leaf.path} disabled={frozen} checked={checked} onChange={() => toggleSource(selection)}>{leaf.path}：{leaf.preview}</Checkbox>;
              })}
            </Space></List.Item>}
          /> : null}
          {!candidates.resumes.length && !candidates.interview_notes.length && !candidates.mock_turns.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可选择的已保存原始来源" /> : null}
        </Space>
      ) : null}
      <Divider />
      <Title level={5}>补充你的明确原始陈述</Title>
      <Space.Compact style={{ width: '100%' }}>
        <Input aria-label="用户明确原始陈述" disabled={frozen} value={assertion} onChange={(event) => setAssertion(event.target.value)} placeholder="例如：这是我本人负责的工作内容" />
        <Button disabled={frozen || !assertion.trim()} onClick={addAssertion}>加入</Button>
      </Space.Compact>
      {draft.assertions.map((item) => <Tag key={item} closable={!frozen} onClose={() => discardChangedInput({ assertions: draft.assertions.filter((value) => value !== item) })} style={{ marginTop: 8 }}>用户陈述 · {item}</Tag>)}
      <Divider />
      {sourceSelected && !draft.proposal && !showPreview ? (
        <Space>
          <Button onClick={() => { setAuthoringMode('proposal'); setShowPreview(true); }}>使用 AI 整理</Button>
          {draft.entrypoint === 'ui' ? <Button onClick={() => { setAuthoringMode('manual'); setShowPreview(true); }}>手动编写并保存</Button> : null}
        </Space>
      ) : null}
      {sourceSelected && !draft.proposal && showPreview && authoringMode === 'proposal' ? (
        <>
          <Alert type="info" message="生成建议前请确认来源" description="将只发送你勾选的原文片段和明确陈述。" style={{ marginBottom: 12 }} />
          <Checkbox disabled={frozen} checked={previewConfirmed} onChange={(event) => setPreviewConfirmed(event.target.checked)}>我已确认上述原始来源和陈述</Checkbox>
          <div style={{ marginTop: 12 }}><Button data-story-audit={`${draft.entrypoint}-generate`} type="primary" disabled={!previewConfirmed || frozen} loading={busy} onClick={() => void generate()}>生成故事建议</Button></div>
        </>
      ) : null}
      {sourceSelected && !draft.proposal && showPreview && authoringMode === 'manual' ? (
        <>
          <Alert type="info" message="手动保存前请确认原始来源" description="手动保存不会调用 AI；所选来源会随新版本冻结保存。" style={{ marginBottom: 12 }} />
          <Input
            aria-label="手动故事标题"
            disabled={frozen}
            value={draft.manualContent.title}
              onChange={(event) => update({ manualContent: { ...draft.manualContent, title: event.target.value }, manualSavePayload: null })}
            placeholder="故事标题"
            style={{ marginBottom: 8 }}
          />
          {draft.manualContent.blocks.map((block, index) => (
            <Input.TextArea
              key={block.kind}
              aria-label={`手动故事${({ situation: '情境', task: '任务', action: '行动', result: '结果', reflection: '复盘' } as const)[block.kind]}`}
              disabled={frozen}
              value={block.text}
              onChange={(event) => update({
                manualContent: {
                  ...draft.manualContent,
                  blocks: draft.manualContent.blocks.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item),
                },
                manualSavePayload: null,
              })}
              placeholder={block.kind === 'reflection' ? '你的观点或复盘，不会冒充外部事实' : `用原始证据支持的${({ situation: '情境', task: '任务', action: '行动', result: '结果' } as const)[block.kind as Exclude<typeof block.kind, 'reflection'>]}`}
              autoSize={{ minRows: 2, maxRows: 6 }}
              style={{ marginBottom: 8 }}
            />
          ))}
          <Input.TextArea
            aria-label="手动能力标签"
            disabled={frozen}
            value={draft.manualContent.capability_labels.join('\n')}
            onChange={(event) => update({ manualContent: { ...draft.manualContent, capability_labels: event.target.value.split('\n').filter(Boolean) }, manualSavePayload: null })}
            placeholder="能力标签，每行一个（可选）"
            autoSize={{ minRows: 1, maxRows: 4 }}
            style={{ marginBottom: 8 }}
          />
          <Input.TextArea
            aria-label="手动适用问题"
            disabled={frozen}
            value={draft.manualContent.applicable_questions.join('\n')}
            onChange={(event) => update({ manualContent: { ...draft.manualContent, applicable_questions: event.target.value.split('\n').filter(Boolean) }, manualSavePayload: null })}
            placeholder="适用问题，每行一个（可选）"
            autoSize={{ minRows: 1, maxRows: 4 }}
            style={{ marginBottom: 8 }}
          />
          {manualTargets.length > 0 ? (
            <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
              <Text strong>逐项选择原始证据</Text>
              <Text type="secondary">每个已填写目标都必须明确绑定一条已选原文或你的明确陈述；系统不会自动复制第一条来源。</Text>
              {manualTargets.map((target) => {
                const targetKey = manualEvidenceKey(target);
                return (
                  <label key={targetKey} style={{ display: 'grid', gap: 4 }}>
                    <Text>{target.label}</Text>
                    <select
                      aria-label={`手动证据：${target.label}`}
                      data-testid={`manual-evidence-${target.target_kind}-${target.target_id}`}
                      disabled={frozen}
                      value={draft.manualEvidenceBindings[targetKey] ?? ''}
                      onChange={(event) => update({
                        manualEvidenceBindings: { ...draft.manualEvidenceBindings, [targetKey]: event.target.value },
                        manualSavePayload: null,
                      })}
                    >
                      <option value="">请选择原始证据</option>
                      {manualEvidenceSources.map((source) => <option key={source.key} value={source.key}>{source.label}</option>)}
                    </select>
                  </label>
                );
              })}
            </Space>
          ) : null}
          {!draft.manualContent.blocks.some((block) => block.kind === 'result' && block.text.trim()) ? <Alert type="info" showIcon message="尚未填写结果：保存时会标记为“请补充可验证的结果或影响”。" style={{ marginBottom: 12 }} /> : null}
          <Button type="primary" disabled={frozen || !draft.manualContent.title.trim() || !draft.manualContent.blocks.some((block) => block.text.trim())} loading={busy} onClick={() => void saveManualStory()}>确认手动保存故事版本</Button>
        </>
      ) : null}
      {!sourceSelected && !draft.proposal ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择至少一条原始证据后，才能生成建议" /> : null}
      {draft.proposal?.proposal_status === 'safe_empty' ? (
        <Alert
          type="info"
          showIcon
          message="暂无可验证的故事草稿"
          description="你可以补充原始证据或明确陈述后重新开始。"
          action={<Button size="small" onClick={restartAfterSafeEmpty}>补充来源并重新开始</Button>}
        />
      ) : null}
      {normalProposal ? (
        <>
          <Divider />
          <Title level={4}>审阅并编辑故事草稿</Title>
          <Input
            aria-label="故事标题"
            disabled={frozen}
            value={(draft.editedContent ?? editableContent(normalProposal.content)).title}
            onChange={(event) => update({
              editedContent: { ...(draft.editedContent ?? editableContent(normalProposal.content)), title: event.target.value },
            })}
            style={{ marginBottom: 12 }}
          />
          {(draft.editedContent ?? editableContent(normalProposal.content)).blocks.map((block, index) => (
            <Input.TextArea
              key={normalProposal.content.blocks[index]?.id ?? index}
              aria-label={`故事区块 ${index + 1}`}
              disabled={frozen}
              value={block.text}
              onChange={(event) => {
                const current = draft.editedContent ?? editableContent(normalProposal.content);
                const blocks = current.blocks.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item);
                update({ editedContent: { ...current, blocks } });
              }}
              autoSize={{ minRows: 2, maxRows: 6 }}
              style={{ marginBottom: 8 }}
            />
          ))}
          <Alert type="info" showIcon message="确认前可编辑标题和故事区块；证据引用仍会在保存时严格复核。" style={{ marginBottom: 12 }} />
          <Button data-story-audit={`${draft.entrypoint}-confirm`} type="primary" loading={busy} disabled={frozen} onClick={() => void confirm()}>确认保存这个故事版本</Button>
        </>
      ) : null}
    </Drawer>
  );
}
