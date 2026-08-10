import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Checkbox, Divider, Drawer, Empty, Input, List, Space, Spin, Tag, Typography, message } from 'antd';
import { listNotes } from '@/services/notes';
import {
  confirmInterviewStoryProposal,
  createInterviewStoryProposal,
  InterviewStoryError,
} from '@/services/interviewStories';
import type {
  InterviewStoryClientEvidenceLink,
  InterviewStoryContent,
  InterviewStoryEditableContent,
  InterviewStoryProposalAttempt,
  InterviewStorySourceSelection,
} from '@/types/interviewStory';
import type { InterviewNote } from '@/types/note';

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
  idempotencyKey: string;
  attemptId: number | null;
  proposal: InterviewStoryProposalAttempt['proposal'] | null;
  editedContent: InterviewStoryEditableContent | null;
  resultUnknown: boolean;
  confirmationToken: string | null;
  error: string | null;
}

interface Props {
  open: boolean;
  draft: InterviewStoryDraft;
  onDraftChange: (draft: InterviewStoryDraft | null) => void;
  onClose: () => void;
}

const NOTE_FIELDS: Array<{ path: '/questions' | '/self_reflection' | '/difficulty_points' | '/mood'; label: string }> = [
  { path: '/questions', label: '选择问题' },
  { path: '/self_reflection', label: '选择自我复盘' },
  { path: '/difficulty_points', label: '选择困难点' },
  { path: '/mood', label: '选择情绪记录' },
];

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
    idempotencyKey: key('story'),
    attemptId: null,
    proposal: null,
    editedContent: null,
    resultUnknown: false,
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

function clientEvidence(links: NonNullable<InterviewStoryProposalAttempt['proposal']>['evidence_links']): InterviewStoryClientEvidenceLink[] {
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

export default function InterviewStoryDrawer({ open, draft, onDraftChange, onClose }: Props) {
  const [notes, setNotes] = useState<InterviewNote[]>([]);
  const [notesLoading, setNotesLoading] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [previewConfirmed, setPreviewConfirmed] = useState(false);
  const [assertion, setAssertion] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setNotesLoading(true);
    void listNotes().then(setNotes).catch(() => setNotes([])).finally(() => setNotesLoading(false));
  }, [open]);

  const sourceSelected = draft.selections.length > 0 || draft.assertions.length > 0;
  const frozen = draft.resultUnknown || busy;
  const scopedNote = useMemo(() => notes.find((note) => note.id === draft.reviewNoteId), [draft.reviewNoteId, notes]);

  const update = (changes: Partial<InterviewStoryDraft>) => onDraftChange({ ...draft, ...changes });

  const toggleNoteField = (note: InterviewNote, path: InterviewStorySourceSelection['path']) => {
    if (frozen) return;
    const selection = { source_kind: 'interview_note' as const, source_id: note.id, path };
    const exists = draft.selections.some((item) => item.source_kind === selection.source_kind && item.source_id === selection.source_id && item.path === path);
    update({
      selections: exists
        ? draft.selections.filter((item) => !(item.source_kind === selection.source_kind && item.source_id === selection.source_id && item.path === path))
        : [...draft.selections, selection],
      proposal: null,
      editedContent: null,
      attemptId: null,
      resultUnknown: false,
      error: null,
    });
    setShowPreview(false);
  };

  const addAssertion = () => {
    const value = assertion.trim();
    if (!value || frozen) return;
    update({ assertions: [...draft.assertions, value], proposal: null, editedContent: null, attemptId: null, resultUnknown: false, error: null });
    setAssertion('');
    setShowPreview(false);
  };

  const generate = async () => {
    if (!sourceSelected || !previewConfirmed) return;
    setBusy(true);
    try {
      const response = await createInterviewStoryProposal({
        target_story_id: draft.targetStoryId,
        expected_current_version_id: draft.expectedCurrentVersionId,
        expected_story_revision: draft.expectedStoryRevision,
        selections: draft.selections,
        assertions: draft.assertions,
        idempotency_key: draft.idempotencyKey,
        ...(draft.reviewNoteId ? { entry_context: { review_note_id: draft.reviewNoteId } } : {}),
      }, draft.entrypoint);
      if (!('proposal' in response) || response.attempt_status === 'generating' || response.attempt_status === 'provider_unknown') {
        update({ attemptId: response.id, resultUnknown: true, error: 'AI 结果待确认，请使用原尝试重试。' });
        return;
      }
      update({
        attemptId: response.id,
        proposal: response.proposal ?? null,
        editedContent: response.proposal?.proposal_status === 'normal' ? editableContent(response.proposal.content) : null,
        resultUnknown: false,
        error: null,
      });
    } catch (error) {
      const safe = safeMessage(error);
      if (error instanceof InterviewStoryError && error.code === 'story_unverifiable') {
        onDraftChange(createInterviewStoryDraft(draft.entrypoint, draft.reviewNoteId, {
          targetStoryId: draft.targetStoryId ?? undefined,
          expectedCurrentVersionId: draft.expectedCurrentVersionId ?? undefined,
          expectedStoryRevision: draft.expectedStoryRevision ?? undefined,
        }));
      } else {
        update({ resultUnknown: true, error: safe });
      }
      message.error(safe);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!draft.proposal || !draft.attemptId) return;
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
      update({ confirmationToken: token, resultUnknown: true, error: safe });
      message.error(safe);
    } finally {
      setBusy(false);
    }
  };

  const notesToShow = scopedNote ? [scopedNote] : notes;
  return (
    <Drawer open={open} width={720} destroyOnClose={false} onClose={onClose} title={draft.entrypoint === 'pilot' ? 'Pilot · 整理面试故事' : '整理面试故事'}>
      <Alert
        type="info"
        showIcon
        message="先选择原始证据，再确认发送给 AI"
        description="不会自动选择来源，不会写入知识库；每一条保存内容都需要原始证据或你的明确陈述。"
        style={{ marginBottom: 16 }}
      />
      {draft.error ? <Alert type="warning" showIcon message={draft.error} action={draft.resultUnknown ? <Button size="small" onClick={() => void generate()}>使用原尝试重试</Button> : undefined} style={{ marginBottom: 16 }} /> : null}
      <Title level={5}>选择已保存的面试复盘原文</Title>
      {notesLoading ? <Spin /> : null}
      {!notesLoading && notesToShow.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有可选择的已保存面试复盘" /> : null}
      <List
        size="small"
        dataSource={notesToShow}
        renderItem={(note) => (
          <List.Item>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Text strong>{note.company} · {note.position}</Text>
              {NOTE_FIELDS.map((field) => {
                const value = note[field.path.slice(1) as keyof InterviewNote];
                const selectable = typeof value === 'string' && value.trim().length > 0;
                const checked = draft.selections.some((item) => item.source_kind === 'interview_note' && item.source_id === note.id && item.path === field.path);
                return (
                  <Checkbox key={field.path} disabled={!selectable || frozen} checked={checked} onChange={() => toggleNoteField(note, field.path)}>
                    {field.label}{selectable ? `：${String(value).slice(0, 72)}` : '（暂无原文）'}
                  </Checkbox>
                );
              })}
            </Space>
          </List.Item>
        )}
      />
      <Divider />
      <Title level={5}>补充你的明确原始陈述</Title>
      <Space.Compact style={{ width: '100%' }}>
        <Input aria-label="用户明确原始陈述" disabled={frozen} value={assertion} onChange={(event) => setAssertion(event.target.value)} placeholder="例如：这是我本人负责的工作内容" />
        <Button disabled={frozen || !assertion.trim()} onClick={addAssertion}>加入</Button>
      </Space.Compact>
      {draft.assertions.map((item) => <Tag key={item} closable={!frozen} onClose={() => update({ assertions: draft.assertions.filter((value) => value !== item) })} style={{ marginTop: 8 }}>用户陈述 · {item}</Tag>)}
      <Divider />
      {sourceSelected && !draft.proposal && !showPreview ? (
        <Button onClick={() => setShowPreview(true)}>查看冻结来源</Button>
      ) : null}
      {sourceSelected && !draft.proposal && showPreview ? (
        <>
          <Alert type="info" message="生成建议前请确认来源" description="将只发送你勾选的原文片段和明确陈述。" style={{ marginBottom: 12 }} />
          <Checkbox disabled={frozen} checked={previewConfirmed} onChange={(event) => setPreviewConfirmed(event.target.checked)}>我已确认上述原始来源和陈述</Checkbox>
          <div style={{ marginTop: 12 }}><Button type="primary" disabled={!previewConfirmed || frozen} loading={busy} onClick={() => void generate()}>生成故事建议</Button></div>
        </>
      ) : null}
      {!sourceSelected && !draft.proposal ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择至少一条原始证据后，才能生成建议" /> : null}
      {draft.proposal?.proposal_status === 'safe_empty' ? <Alert type="info" showIcon message="暂无可验证的故事草稿" description="你可以补充原始证据或明确陈述后重新开始。" /> : null}
      {draft.proposal?.proposal_status === 'normal' ? (
        <>
          <Divider />
          <Title level={4}>审阅并编辑故事草稿</Title>
          <Input
            aria-label="故事标题"
            disabled={frozen}
            value={(draft.editedContent ?? editableContent(draft.proposal.content)).title}
            onChange={(event) => update({
              editedContent: { ...(draft.editedContent ?? editableContent(draft.proposal!.content)), title: event.target.value },
            })}
            style={{ marginBottom: 12 }}
          />
          {(draft.editedContent ?? editableContent(draft.proposal.content)).blocks.map((block, index) => (
            <Input.TextArea
              key={draft.proposal!.content.blocks[index]?.id ?? index}
              aria-label={`故事区块 ${index + 1}`}
              disabled={frozen}
              value={block.text}
              onChange={(event) => {
                const current = draft.editedContent ?? editableContent(draft.proposal!.content);
                const blocks = current.blocks.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item);
                update({ editedContent: { ...current, blocks } });
              }}
              autoSize={{ minRows: 2, maxRows: 6 }}
              style={{ marginBottom: 8 }}
            />
          ))}
          <Alert type="info" showIcon message="确认前可编辑标题和故事区块；证据引用仍会在保存时严格复核。" style={{ marginBottom: 12 }} />
          <Button type="primary" loading={busy} disabled={frozen} onClick={() => void confirm()}>确认保存这个故事版本</Button>
        </>
      ) : null}
    </Drawer>
  );
}
