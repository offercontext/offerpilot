import { useEffect, useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, Form, Input, Radio, InputNumber, Select, App as AntApp, Empty } from 'antd';
import { AudioOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  listMockSessions,
  createMockSession,
  endMockSession,
} from '@/services/mock';
import type { MockSession, MockConfig, MockFeedback } from '@/types/mock';
import MockChat from './MockChat';
import MockResultCard from './MockResultCard';
import styles from './MockStudio.module.css';

type Stage = 'setup' | 'running' | 'result';

interface Props {
  /** Optional pre-filled config when launched from "针对此投递模拟面试". */
  prefill?: Partial<MockConfig> | null;
  /** Jump to a question-bank item (handled by AppShell switching to questions view). */
  onJumpQuestion: (id: number) => void;
  /** Clear the prefill once consumed. */
  onConsumePrefill?: () => void;
}

export default function MockStudioView({ prefill, onJumpQuestion, onConsumePrefill }: Props) {
  const { message: toast } = AntApp.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [stage, setStage] = useState<Stage>('setup');
  const [activeId, setActiveId] = useState<number | null>(null);
  const [result, setResult] = useState<{ session: MockSession; feedback: MockFeedback } | null>(null);
  const [ending, setEnding] = useState(false);
  const [savedNoteId, setSavedNoteId] = useState<number | null>(null);

  const sessionsQ = useQuery({ queryKey: ['mock-sessions'], queryFn: () => listMockSessions() });

  const sessions = sessionsQ.data ?? [];

  const inProgress = useMemo(() => sessions.filter((s) => s.status === 'in_progress'), [sessions]);
  const completed = useMemo(() => sessions.filter((s) => s.status === 'completed'), [sessions]);

  // Apply prefill when provided (e.g. launched from an application detail).
  useEffect(() => {
    if (prefill) {
      form.setFieldsValue({
        role: prefill.role,
        company: prefill.company,
        application_id: prefill.application_id,
        round_type: prefill.round_type ?? 'technical',
        difficulty: prefill.difficulty ?? 'medium',
        question_count: prefill.question_count ?? 5,
        duration_min: prefill.duration_min ?? 30,
        question_source: prefill.question_source ?? 'mixed',
      });
      onConsumePrefill?.();
    }
  }, [prefill, form, onConsumePrefill]);

  const createMut = useMutation({
    mutationFn: (cfg: MockConfig) => createMockSession(cfg),
    onSuccess: (resp) => {
      setActiveId(resp.session.id);
      setStage('running');
      setResult(null);
      setSavedNoteId(null);
      qc.invalidateQueries({ queryKey: ['mock-sessions'] });
      toast.success('模拟面试已开始，回答面试官的第一个问题吧。');
    },
    onError: () => toast.error('创建会话失败，请检查是否已配置 AI API Key。'),
  });

  const endMut = useMutation({
    mutationFn: ({ id, autoSave }: { id: number; autoSave: boolean }) =>
      endMockSession(id, autoSave),
    onSuccess: (resp) => {
      setResult({ session: resp.session, feedback: resp.feedback });
      setStage('result');
      setEnding(false);
      qc.invalidateQueries({ queryKey: ['mock-sessions'] });
      if (resp.parse_error) {
        toast.warning('评分已生成，但部分内容解析降级，请人工核对。');
      }
      if (resp.saved_note_id) {
        setSavedNoteId(resp.saved_note_id);
        toast.success('已保存为面试复盘记录。');
      }
    },
    onError: (err: unknown) => {
      setEnding(false);
      // Surface the backend's specific reason (e.g. "该模拟面试未绑定投递，
      // 无法保存为面试复盘") instead of a generic "评分失败" so the user knows
      // whether it's a network/scoring issue or a save-blocked-by-config issue.
      let msg = '评分失败，可能 AI 未配置或超时，会话已标记中止。';
      if (err && typeof err === 'object' && 'response' in err) {
        const resp = (err as { response?: { data?: { error?: string } } }).response;
        if (resp?.data?.error) {
          msg = resp.data.error;
        }
      }
      toast.error(msg);
      qc.invalidateQueries({ queryKey: ['mock-sessions'] });
    },
  });

  function handleStart(values: MockConfig) {
    createMut.mutate({
      application_id: values.application_id,
      role: values.role?.trim() || '通用工程师',
      company: values.company?.trim(),
      round_type: values.round_type,
      difficulty: values.difficulty,
      question_count: values.question_count,
      duration_min: values.duration_min,
      question_source: values.question_source,
    });
  }

  function handleEnd(autoSave: boolean) {
    if (activeId == null) return;
    setEnding(true);
    endMut.mutate({ id: activeId, autoSave });
  }

  function handleSelectSession(s: MockSession) {
    if (s.status === 'in_progress') {
      setActiveId(s.id);
      setStage('running');
      setResult(null);
      setSavedNoteId(null);
    } else if (s.status === 'completed' && s.feedback) {
      try {
        const fb = JSON.parse(s.feedback) as MockFeedback;
        setActiveId(s.id);
        setResult({ session: s, feedback: fb });
        setSavedNoteId(null); // reviewing a past session; allow re-saving if bound to an app
        setStage('result');
      } catch {
        toast.error('该会话评分数据损坏，无法展示。');
      }
    } else {
      toast.info('该会话已中止，无法查看。');
    }
  }

  function handleRetry() {
    if (!result) return;
    const prev = result.session;
    form.setFieldsValue({
      role: prev.role,
      company: prev.company,
      round_type: prev.round_type,
      difficulty: prev.difficulty,
      question_count: prev.question_count,
      duration_min: prev.duration_min,
      question_source: prev.question_source,
    });
    setResult(null);
    setActiveId(null);
    setSavedNoteId(null);
    setStage('setup');
  }

  function handleClose() {
    setResult(null);
    setActiveId(null);
    setStage('setup');
  }

  function handleJumpQuestion(id: number) {
    onJumpQuestion(id);
  }

  const active = activeId ? sessions.find((s) => s.id === activeId) : null;

  return (
    <div className={styles.layout}>
      {/* Sidebar: session list */}
      <aside className={styles.sidebarList}>
        <div className={styles.sidebarTitle}>
          <span className={styles.sidebarTitleText}>
            <AudioOutlined /> 模拟面试
          </span>
          <Button
            size="small"
            type="text"
            icon={<PlusOutlined />}
            onClick={() => {
              setActiveId(null);
              setResult(null);
              setStage('setup');
            }}
            aria-label="新建模拟面试"
          />
        </div>

        {inProgress.length > 0 && (
          <>
            <div className={styles.sidebarSub}>进行中 {inProgress.length}</div>
            {inProgress.map((s) => (
              <SessionRow
                key={s.id}
                s={s}
                active={activeId === s.id}
                onClick={() => handleSelectSession(s)}
              />
            ))}
          </>
        )}

        {completed.length > 0 && (
          <>
            <div className={styles.sidebarSub}>已完成 {completed.length}</div>
            {completed.slice(0, 12).map((s) => (
              <SessionRow
                key={s.id}
                s={s}
                active={activeId === s.id}
                onClick={() => handleSelectSession(s)}
              />
            ))}
          </>
        )}

        {sessions.length === 0 && (
          <div style={{ padding: '24px 12px', color: 'var(--op-muted)', fontSize: 13, textAlign: 'center' }}>
            还没有模拟面试记录
          </div>
        )}
      </aside>

      {/* Main: one of three stages */}
      <main className={styles.main}>
        {stage === 'setup' && (
          <div className={styles.card}>
            <div className={styles.eyebrow}>配置模拟面试</div>
            <h2 className={styles.title}>设定一场按真实节奏进行的对话式模拟</h2>
            <p className={styles.subtitle}>
              AI 将扮演目标岗位的面试官，逐题追问、施压、换方向；结束后给出五维评分与下一步行动建议，并可一键沉淀为面试复盘。
            </p>
            <Form form={form} layout="vertical" className={styles.form} onFinish={handleStart}>
              <div className={styles.formRow}>
                <Form.Item
                  name="role"
                  label="目标岗位"
                  rules={[{ required: true, message: '请填写目标岗位' }]}
                >
                  <Input placeholder="如：后端开发 / 前端 / 产品经理" />
                </Form.Item>
                <Form.Item name="company" label="目标公司（可选）">
                  <Input placeholder="如：字节跳动" />
                </Form.Item>
              </div>

              <div className={styles.formRow}>
                <Form.Item name="round_type" label="轮次类型" initialValue="technical">
                  <Radio.Group>
                    <Radio.Button value="technical">技术</Radio.Button>
                    <Radio.Button value="behavioral">行为</Radio.Button>
                    <Radio.Button value="coding">手撕</Radio.Button>
                    <Radio.Button value="hr">HR</Radio.Button>
                    <Radio.Button value="mixed">混合</Radio.Button>
                  </Radio.Group>
                </Form.Item>
                <Form.Item name="difficulty" label="难度" initialValue="medium">
                  <Radio.Group>
                    <Radio.Button value="easy">简单</Radio.Button>
                    <Radio.Button value="medium">中等</Radio.Button>
                    <Radio.Button value="hard">困难</Radio.Button>
                  </Radio.Group>
                </Form.Item>
              </div>

              <div className={styles.formRow}>
                <Form.Item name="question_count" label="题数" initialValue={5} tooltip="0 表示不限，直到你说「结束面试」">
                  <InputNumber min={0} max={20} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="duration_min" label="时长（分钟）" initialValue={30} tooltip="0 表示不限">
                  <InputNumber min={0} max={120} style={{ width: '100%' }} />
                </Form.Item>
              </div>

              <div className={styles.formRow}>
                <Form.Item name="question_source" label="出题来源" initialValue="mixed">
                  <Select
                    options={[
                      { value: 'mixed', label: '混合（题库 + 知识库 + 历史薄弱点）' },
                      { value: 'bank', label: '题库' },
                      { value: 'knowledge', label: '知识库' },
                      { value: 'notes', label: '历史复盘薄弱点' },
                    ]}
                  />
                </Form.Item>
              </div>

              <div className={styles.preview}>
                <ThunderboltOutlined className={styles.previewIcon} />
                {(() => {
                  const src = form.getFieldValue('question_source') ?? 'mixed';
                  const label: Record<string, string> = {
                    mixed: '将综合使用题库 / 知识库 / 历史复盘薄弱点出题',
                    bank: '将从你的题库按难度抽题',
                    knowledge: '将基于知识库片段设计提问',
                    notes: '将针对历史复盘里的薄弱点出题',
                  };
                  return label[src] ?? label.mixed;
                })()}
              </div>

              <Form.Item style={{ marginBottom: 0, marginTop: 4 }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={createMut.isPending}
                  className="op-ai-btn"
                  size="large"
                  icon={<ThunderboltOutlined />}
                  style={{ width: '100%' }}
                >
                  开始模拟面试 →
                </Button>
              </Form.Item>
            </Form>
          </div>
        )}

        {stage === 'running' && active && (
          <div className={styles.card}>
            <div className={styles.runningHeader}>
              <div>
                <div className={styles.eyebrow}>模拟面试进行中</div>
                <h2 className={styles.title}>
                  {active.role}
                  {active.company ? ` · ${active.company}` : ''}
                </h2>
              </div>
              <Button
                danger
                type="primary"
                className={styles.endBtn}
                loading={ending}
                onClick={() => handleEnd(false)}
              >
                结束并评分
              </Button>
            </div>
            <MockChat
              conversationId={active.conversation_id}
              questionCount={active.question_count}
              questionIndex={active.question_index}
              disabled={ending}
              onProgress={() => qc.invalidateQueries({ queryKey: ['mock-sessions'] })}
            />
          </div>
        )}

        {stage === 'result' && result && (
          <MockResultCard
            session={result.session}
            feedback={result.feedback}
            saving={endMut.isPending}
            savedNoteId={savedNoteId}
            onSaveNote={() => handleEnd(true)}
            onRetry={handleRetry}
            onClose={handleClose}
            onJumpQuestion={handleJumpQuestion}
          />
        )}

        {stage === 'running' && !active && (
          <div className={styles.card}>
            <Empty description="未找到该会话" />
          </div>
        )}
      </main>
    </div>
  );
}

function SessionRow({
  s,
  active,
  onClick,
}: {
  s: MockSession;
  active: boolean;
  onClick: () => void;
}) {
  const date = dayjs(s.started_at).format('MM-DD HH:mm');
  return (
    <button
      type="button"
      className={`${styles.sessionItem} ${active ? styles.active : ''}`}
      onClick={onClick}
    >
      <span className={styles.sessionTitle}>
        {s.role}
        {s.company ? ` · ${s.company}` : ''}
      </span>
      <span className={styles.sessionMeta}>
        {date} · {s.round_type}/{s.difficulty}
        {s.status === 'completed' && s.score_overall != null ? ` · ${s.score_overall}分` : ''}
      </span>
    </button>
  );
}
