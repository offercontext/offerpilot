import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Form,
  Input,
  Progress,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  App as AntApp,
} from 'antd';
import { ArrowLeftOutlined, CopyOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import type { Application } from '@/types/application';
import type {
  MaterialKitChecklistItem,
  MaterialKitContent,
  MaterialKitMessage,
  MaterialKitStatus,
  MaterialKitViewModel,
} from '@/types/materialKit';
import type { Resume } from '@/types/resume';
import {
  generateApplicationMaterialKit,
  getApplicationMaterialKit,
  updateMaterialKit,
} from '@/services/materialKits';
import { listResumes } from '@/services/resumes';
import styles from './MaterialKitDrawer.module.css';

interface Props {
  application: Application | null;
  open: boolean;
  onClose: () => void;
}

interface GenerateVariables {
  applicationID: number;
  resumeID: number;
  jdText: string;
  overwrite: boolean;
}

interface SaveVariables {
  applicationID: number;
  kitID: number;
  resumeID: number | undefined;
  jdSnapshot: string;
  status: MaterialKitStatus;
  content: MaterialKitContent;
}

const STATUS_OPTIONS: Array<{ label: string; value: MaterialKitStatus }> = [
  { label: '草稿', value: 'draft' },
  { label: '已准备', value: 'ready' },
  { label: '已投递', value: 'submitted' },
];

function createDefaultContent(): MaterialKitContent {
  return {
    resume_advice: {
      summary: '',
      highlights: [],
      rewrite_bullets: [],
      gaps: [],
      notes: '',
    },
    messages: [
      { type: 'recruiter_email', title: 'HR 邮件', body: '', notes: '' },
      { type: 'referral_message', title: '内推私信', body: '', notes: '' },
      { type: 'application_note', title: '投递备注', body: '', notes: '' },
    ],
    checklist: [
      { id: 'confirm_jd', label: '确认岗位 JD 和投递入口', done: false },
      { id: 'select_resume', label: '选择最匹配的简历版本', done: false },
      { id: 'tailor_resume', label: '按岗位关键词调整简历', done: false },
      { id: 'prepare_message', label: '准备沟通话术和备注', done: false },
      { id: 'submit_application', label: '完成投递', done: false },
      { id: 'set_followup', label: '设置跟进提醒', done: false },
    ],
  };
}

function cloneContent(content: MaterialKitContent): MaterialKitContent {
  return {
    resume_advice: {
      summary: content.resume_advice.summary || '',
      highlights: [...(content.resume_advice.highlights || [])],
      rewrite_bullets: [...(content.resume_advice.rewrite_bullets || [])],
      gaps: [...(content.resume_advice.gaps || [])],
      notes: content.resume_advice.notes || '',
    },
    messages: (content.messages || []).map((message) => ({ ...message })),
    checklist: (content.checklist || []).map((item) => ({ ...item })),
  };
}

function textToLines(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

function linesToText(value: string[]): string {
  return value.join('\n');
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return '操作失败，请稍后重试';
}

export default function MaterialKitDrawer({ application, open, onClose }: Props) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const applicationID = application?.id;

  const [existingKit, setExistingKit] = useState<MaterialKitViewModel | null>(null);
  const [resumeID, setResumeID] = useState<number | undefined>();
  const [jdSnapshot, setJdSnapshot] = useState('');
  const [status, setStatus] = useState<MaterialKitStatus>('draft');
  const [content, setContent] = useState<MaterialKitContent>(() => createDefaultContent());
  const [actionError, setActionError] = useState<string | null>(null);

  const resetEditor = (nextApplication: Application | null) => {
    setExistingKit(null);
    setResumeID(undefined);
    setJdSnapshot(nextApplication?.notes || '');
    setStatus('draft');
    setContent(createDefaultContent());
    setActionError(null);
  };

  const applyKitToEditor = (kit: MaterialKitViewModel) => {
    setExistingKit(kit);
    setResumeID(kit.resume_id);
    setJdSnapshot(kit.jd_snapshot);
    setStatus(kit.status);
    setContent(cloneContent(kit.content));
    setActionError(null);
  };

  const kitQuery = useQuery({
    queryKey: ['application-material-kit', applicationID],
    queryFn: () => getApplicationMaterialKit(applicationID!),
    enabled: open && Boolean(applicationID),
  });

  const resumesQuery = useQuery({
    queryKey: ['resumes'],
    queryFn: () => listResumes(),
    enabled: open,
  });

  useEffect(() => {
    resetEditor(open ? application : null);
  }, [applicationID, application?.notes, open]);

  useEffect(() => {
    if (!open || !applicationID || !kitQuery.isSuccess) return;

    const kit = kitQuery.data;
    if (!kit) {
      resetEditor(application);
      return;
    }

    if (kit.application_id !== applicationID) return;
    applyKitToEditor(kit);
  }, [application, applicationID, kitQuery.data, kitQuery.isSuccess, open]);

  useEffect(() => {
    if (!kitQuery.isError) return;

    setExistingKit(null);
    setResumeID(undefined);
    setJdSnapshot(application?.notes || '');
    setStatus('draft');
    setContent(createDefaultContent());
    setActionError(getErrorMessage(kitQuery.error));
  }, [application?.notes, kitQuery.error, kitQuery.isError]);

  const completion = useMemo(() => {
    const checklist = content.checklist || [];
    if (checklist.length === 0) return 0;
    const done = checklist.filter((item) => item.done).length;
    return Math.round((done / checklist.length) * 100);
  }, [content.checklist]);

  const generateMutation = useMutation({
    mutationFn: ({ applicationID: requestedApplicationID, resumeID: requestedResumeID, jdText, overwrite }: GenerateVariables) =>
      generateApplicationMaterialKit(requestedApplicationID, {
        resume_id: requestedResumeID,
        jd_text: jdText,
        overwrite,
      }),
    onSuccess: (kit, variables) => {
      queryClient.setQueryData(['application-material-kit', kit.application_id], kit);

      if (kit.application_id !== applicationID || variables.applicationID !== applicationID) return;

      applyKitToEditor(kit);
      message.success('材料包已生成');
    },
    onError: (error, variables) => {
      if (variables.applicationID === applicationID) {
        setActionError(getErrorMessage(error));
      }
    },
  });

  const saveMutation = useMutation({
    mutationFn: ({ kitID, resumeID: requestedResumeID, jdSnapshot, status, content }: SaveVariables) =>
      updateMaterialKit(kitID, {
        resume_id: requestedResumeID,
        jd_snapshot: jdSnapshot,
        status,
        content_json: content,
      }),
    onSuccess: (kit, variables) => {
      queryClient.setQueryData(['application-material-kit', kit.application_id], kit);

      if (kit.application_id !== applicationID || variables.applicationID !== applicationID) return;

      applyKitToEditor(kit);
      message.success('材料包已保存');
    },
    onError: (error, variables) => {
      if (variables.applicationID === applicationID) {
        setActionError(getErrorMessage(error));
      }
    },
  });

  const resumeOptions = (resumesQuery.data || []).map((resume: Resume) => ({
    label: resume.name,
    value: resume.id,
  }));

  const canSave = Boolean(existingKit && applicationID && existingKit.application_id === applicationID);
  const generateDisabled = !applicationID || !resumeID || !jdSnapshot.trim();
  const busy = kitQuery.isFetching || generateMutation.isPending || saveMutation.isPending;

  const handleGenerate = () => {
    if (!applicationID || !resumeID || !jdSnapshot.trim()) return;

    generateMutation.mutate({
      applicationID,
      resumeID,
      jdText: jdSnapshot.trim(),
      overwrite: Boolean(existingKit && existingKit.application_id === applicationID),
    });
  };

  const handleSave = () => {
    if (!existingKit || !applicationID || existingKit.application_id !== applicationID) return;

    saveMutation.mutate({
      applicationID,
      kitID: existingKit.id,
      resumeID,
      jdSnapshot,
      status,
      content: cloneContent(content),
    });
  };

  const updateAdvice = <K extends keyof MaterialKitContent['resume_advice']>(
    key: K,
    value: MaterialKitContent['resume_advice'][K],
  ) => {
    setContent((prev) => ({
      ...prev,
      resume_advice: {
        ...prev.resume_advice,
        [key]: value,
      },
    }));
  };

  const updateMessage = (index: number, patch: Partial<MaterialKitMessage>) => {
    setContent((prev) => ({
      ...prev,
      messages: prev.messages.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)),
    }));
  };

  const updateChecklist = (id: string, patch: Partial<MaterialKitChecklistItem>) => {
    setContent((prev) => ({
      ...prev,
      checklist: prev.checklist.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    }));
  };

  const copyMessageBody = async (body: string) => {
    if (!navigator.clipboard?.writeText) {
      message.error('当前浏览器不支持复制');
      return;
    }

    try {
      await navigator.clipboard.writeText(body);
      message.success('已复制到剪贴板');
    } catch {
      message.error('复制失败，请手动复制');
    }
  };

  if (!open) return null;

  return (
    <section className={styles.workspace} aria-label="投递材料包">
      <div className={styles.workspaceHeader}>
        <Button type="link" icon={<ArrowLeftOutlined />} className={styles.backButton} onClick={onClose}>
          返回投递详情
        </Button>
        <Typography.Title level={3} className={styles.workspaceTitle}>
          投递材料包
        </Typography.Title>
      </div>
      <Spin spinning={kitQuery.isFetching && !kitQuery.data}>
        <div className={styles.layout}>
          <aside className={styles.contextPanel}>
            <div>
              <Typography.Text className={styles.eyebrow}>当前岗位</Typography.Text>
              <Typography.Title level={4} className={styles.company}>
                {application?.company_name || '未选择公司'}
              </Typography.Title>
              <Typography.Paragraph className={styles.position}>
                {application?.position_name || '请选择一个投递记录'}
              </Typography.Paragraph>
            </div>

            <Form layout="vertical" className={styles.contextForm}>
              <Form.Item label="简历版本" required>
                <Select
                  placeholder="选择用于生成材料的简历"
                  value={resumeID}
                  onChange={setResumeID}
                  options={resumeOptions}
                  loading={resumesQuery.isFetching}
                  disabled={!open || resumesQuery.isFetching}
                  showSearch
                  optionFilterProp="label"
                />
              </Form.Item>

              <Form.Item label="JD 摘要 / 岗位要求" required>
                <Input.TextArea
                  value={jdSnapshot}
                  onChange={(event) => setJdSnapshot(event.target.value)}
                  placeholder="粘贴岗位 JD，或使用投递备注作为默认内容"
                  rows={8}
                  disabled={!application}
                />
              </Form.Item>

              <Form.Item label="材料状态">
                <Select value={status} onChange={setStatus} options={STATUS_OPTIONS} disabled={!canSave} />
              </Form.Item>
            </Form>

            <div className={styles.progressBlock}>
              <div className={styles.progressHeader}>
                <span>完成度</span>
                <span className="op-tnum">{completion}%</span>
              </div>
              <Progress percent={completion} showInfo={false} className="op-tnum" />
            </div>

            {actionError ? (
              <Alert type="error" showIcon message={actionError} className={styles.alert} />
            ) : null}

            <Space className={styles.actionBar}>
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                onClick={handleGenerate}
                loading={generateMutation.isPending}
                disabled={generateDisabled || busy}
              >
                生成材料包
              </Button>
              <Button
                icon={<SaveOutlined />}
                onClick={handleSave}
                loading={saveMutation.isPending}
                disabled={!canSave || busy}
              >
                保存
              </Button>
            </Space>
          </aside>

          <main className={styles.editorPanel}>
            {!canSave ? (
              <Empty
                className={styles.empty}
                description="选择简历并填写 JD 后，生成材料包即可编辑简历建议、沟通话术和检查清单"
              />
            ) : (
              <div className={styles.sections}>
                <section className={styles.section}>
                  <div className={styles.sectionHeader}>
                    <div>
                      <Typography.Title level={5} className={styles.sectionTitle}>
                        简历优化建议
                      </Typography.Title>
                      <Typography.Text className={styles.sectionHint}>把 AI 建议整理成可执行的修改清单</Typography.Text>
                    </div>
                    <Tag color={status === 'submitted' ? 'green' : status === 'ready' ? 'blue' : 'default'}>
                      {STATUS_OPTIONS.find((item) => item.value === status)?.label}
                    </Tag>
                  </div>

                  <Form layout="vertical">
                    <Form.Item label="整体摘要">
                      <Input.TextArea
                        value={content.resume_advice.summary}
                        onChange={(event) => updateAdvice('summary', event.target.value)}
                        rows={3}
                      />
                    </Form.Item>
                    <Form.Item label="匹配亮点">
                      <Input.TextArea
                        value={linesToText(content.resume_advice.highlights)}
                        onChange={(event) => updateAdvice('highlights', textToLines(event.target.value))}
                        rows={4}
                        placeholder="每行一条亮点"
                      />
                    </Form.Item>
                    <Form.Item label="建议改写的 bullet">
                      <Input.TextArea
                        value={linesToText(content.resume_advice.rewrite_bullets)}
                        onChange={(event) => updateAdvice('rewrite_bullets', textToLines(event.target.value))}
                        rows={4}
                        placeholder="每行一条改写建议"
                      />
                    </Form.Item>
                    <Form.Item label="风险缺口">
                      <Input.TextArea
                        value={linesToText(content.resume_advice.gaps)}
                        onChange={(event) => updateAdvice('gaps', textToLines(event.target.value))}
                        rows={3}
                        placeholder="每行一个待补强点"
                      />
                    </Form.Item>
                    <Form.Item label="备注">
                      <Input.TextArea
                        value={content.resume_advice.notes}
                        onChange={(event) => updateAdvice('notes', event.target.value)}
                        rows={3}
                      />
                    </Form.Item>
                  </Form>
                </section>

                <section className={styles.section}>
                  <Typography.Title level={5} className={styles.sectionTitle}>
                    沟通话术
                  </Typography.Title>
                  <div className={styles.messageList}>
                    {content.messages.map((item, index) => (
                      <div className={styles.messageItem} key={`${item.type}-${index}`}>
                        <div className={styles.messageHeader}>
                          <Input
                            value={item.title}
                            onChange={(event) => updateMessage(index, { title: event.target.value })}
                            className={styles.messageTitleInput}
                          />
                          <Button
                            icon={<CopyOutlined />}
                            onClick={() => copyMessageBody(item.body)}
                            disabled={!item.body.trim()}
                          >
                            复制
                          </Button>
                        </div>
                        <Input.TextArea
                          value={item.body}
                          onChange={(event) => updateMessage(index, { body: event.target.value })}
                          rows={5}
                          placeholder="填写可直接发送的正文"
                        />
                        <Input.TextArea
                          value={item.notes}
                          onChange={(event) => updateMessage(index, { notes: event.target.value })}
                          rows={2}
                          placeholder="内部备注"
                        />
                      </div>
                    ))}
                  </div>
                </section>

                <section className={styles.section}>
                  <Typography.Title level={5} className={styles.sectionTitle}>
                    投递检查清单
                  </Typography.Title>
                  <div className={styles.checklist}>
                    {content.checklist.map((item) => (
                      <div className={styles.checkRow} key={item.id}>
                        <Checkbox
                          checked={item.done}
                          aria-label={`${item.done ? '取消完成' : '标记完成'}：${item.label}`}
                          onChange={(event) => updateChecklist(item.id, { done: event.target.checked })}
                        />
                        <Input
                          value={item.label}
                          onChange={(event) => updateChecklist(item.id, { label: event.target.value })}
                          bordered={false}
                        />
                      </div>
                    ))}
                  </div>
                </section>
              </div>
            )}
          </main>
        </div>
      </Spin>
    </section>
  );
}
