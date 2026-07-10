import { useEffect, useMemo, useState } from 'react';
import { Button, Descriptions, Input, Progress, Space, Tag, message } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateResume } from '@/services/resumes';
import type { CareerIntent, Resume, ResumeContent, UpdateResumeInput } from '@/types/resume';
import dayjs from 'dayjs';
import styles from './ResumeLibraryView.module.css';

interface Props {
  resume: Resume | null;
  open: boolean;
  onClose: () => void;
  onSaved?: (resume: Resume) => void;
}

type SectionKey = 'contact' | 'education' | 'experience' | 'projects' | 'skills' | 'raw_text';

interface SectionMeta {
  key: SectionKey;
  label: string;
  example: string;
  placeholder: string;
  mode: 'json' | 'text';
}

const SECTION_META: SectionMeta[] = [
  {
    key: 'contact',
    label: '联系方式',
    example: '{"name":"Ada","email":"ada@example.com","phone":"13800000000"}',
    placeholder: '填写联系方式 JSON',
    mode: 'json',
  },
  {
    key: 'education',
    label: '教育经历',
    example: '[{"school":"Sample University","degree":"B.S. Computer Science"}]',
    placeholder: '填写教育经历数组 JSON',
    mode: 'json',
  },
  {
    key: 'experience',
    label: '工作经历',
    example: '[{"company":"Sample Tech","title":"Backend Intern","highlights":["Built APIs"]}]',
    placeholder: '填写工作经历数组 JSON',
    mode: 'json',
  },
  {
    key: 'projects',
    label: '项目经历',
    example: '[{"name":"Resume Builder","highlights":["Designed resume CRUD"]}]',
    placeholder: '填写项目经历数组 JSON',
    mode: 'json',
  },
  {
    key: 'skills',
    label: '技能清单',
    example: '["Python","FastAPI","SQLAlchemy"]',
    placeholder: '填写技能数组 JSON',
    mode: 'json',
  },
  {
    key: 'raw_text',
    label: '原始文本',
    example: 'Backend Engineer sample resume with Python, FastAPI, and SQL systems.',
    placeholder: '可保留 PDF 解析文本或手动补充底稿',
    mode: 'text',
  },
];

const SECTION_LABELS: Record<string, string> = {
  career_intent: '求职意向',
  contact: '联系方式',
  education: '教育经历',
  experience: '工作经历',
  projects: '项目经历',
  skills: '技能清单',
};

const SOURCE_LABELS: Record<string, string> = {
  manual: '手动创建',
  dialog: 'Pilot 对话',
  upload: 'PDF 上传',
  sample: '样例开始',
  sample_copy: '样例副本',
};

const EMPTY_DRAFTS: Record<SectionKey, string> = {
  contact: '{}',
  education: '[]',
  experience: '[]',
  projects: '[]',
  skills: '[]',
  raw_text: '',
};

export default function ResumeEditorDrawer({ resume, open, onClose, onSaved }: Props) {
  const qc = useQueryClient();
  const [title, setTitle] = useState('');
  const [targetRoles, setTargetRoles] = useState('');
  const [targetLocations, setTargetLocations] = useState('');
  const [activeSection, setActiveSection] = useState<'career_intent' | SectionKey>('career_intent');
  const [drafts, setDrafts] = useState<Record<SectionKey, string>>(EMPTY_DRAFTS);

  useEffect(() => {
    if (!resume) return;
    const content = normalizeContent(resume.content_json);
    const intent = normalizeCareerIntent(content.career_intent);
    setTitle(resume.title || resume.name || '');
    setTargetRoles((intent.target_roles ?? []).join(', '));
    setTargetLocations((intent.target_locations ?? []).join(', '));
    setDrafts({
      contact: stringifyDraft(content.contact ?? {}),
      education: stringifyDraft(content.education ?? []),
      experience: stringifyDraft(content.experience ?? []),
      projects: stringifyDraft(content.projects ?? []),
      skills: stringifyDraft(content.skills ?? []),
      raw_text: typeof content.raw_text === 'string' ? content.raw_text : resume.parsed_data ?? '',
    });
    setActiveSection('career_intent');
  }, [resume, open]);

  const saveMut = useMutation({
    mutationFn: (input: UpdateResumeInput) => updateResume(resume!.id, input),
    onSuccess: (updated) => {
      message.success('已保存');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      onSaved?.(updated);
      onClose();
    },
    onError: () => message.error('保存失败'),
  });

  const missingLabels = useMemo(
    () => (resume?.missing_sections ?? []).map((item) => SECTION_LABELS[item] ?? item),
    [resume?.missing_sections]
  );

  if (!open || !resume) return null;

  const currentMeta = SECTION_META.find((item) => item.key === activeSection);

  const handleDraftChange = (key: SectionKey, value: string) => {
    setDrafts((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = () => {
    if (!resume) return;
    let content: ResumeContent;
    try {
      content = buildContent({ targetRoles, targetLocations, drafts });
    } catch (error) {
      message.error(error instanceof Error ? error.message : '结构化内容格式错误');
      return;
    }
    saveMut.mutate({
      title: title.trim() || '未命名简历',
      content_json: content,
      career_intent: content.career_intent,
    });
  };

  return (
    <section className={styles.editorWorkspace} aria-label="编辑简历">
      <div className={styles.editorWorkspaceToolbar}>
        <div>
          <Button type="link" className={styles.backButton} onClick={onClose}>
            返回简历库
          </Button>
          <div className={styles.editorWorkspaceTitle}>编辑简历</div>
        </div>
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saveMut.isPending} onClick={handleSave}>
            保存
          </Button>
        </Space>
      </div>

      <div className={styles.editorHeader}>
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="简历标题"
          className={styles.editorTitleInput}
        />
        <div className={styles.editorMeta}>
          <Tag color={resume?.is_master ? 'blue' : 'default'}>{resume?.is_master ? '主简历' : '非主简历'}</Tag>
          <Tag>{SOURCE_LABELS[resume?.source ?? 'manual'] ?? resume?.source}</Tag>
          <span>{resume ? dayjs(resume.created_at).format('YYYY-MM-DD HH:mm') : ''}</span>
        </div>
        <div className={styles.editorCompletion}>
          <Progress percent={resume?.completion_percent ?? 0} size="small" />
          <div className={styles.missingLine}>
            {missingLabels.length ? (
              <>
                <span>待补：</span>
                {missingLabels.map((label) => <Tag key={label}>{label}</Tag>)}
              </>
            ) : (
              <Tag color="success">结构完整</Tag>
            )}
          </div>
        </div>
      </div>

      <Descriptions size="small" column={1} className={styles.editorDescriptions}>
        <Descriptions.Item label="章节大纲">
          <span>求职意向 / 联系方式 / 教育经历 / 工作经历 / 项目经历 / 技能清单 / 原始文本</span>
        </Descriptions.Item>
      </Descriptions>

      <div className={styles.editorGrid}>
        <nav className={styles.sectionNav} aria-label="简历章节">
          <button
            type="button"
            className={activeSection === 'career_intent' ? styles.sectionNavActive : undefined}
            onClick={() => setActiveSection('career_intent')}
          >
            求职意向
          </button>
          {SECTION_META.map((item) => (
            <button
              type="button"
              key={item.key}
              className={activeSection === item.key ? styles.sectionNavActive : undefined}
              onClick={() => setActiveSection(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <section className={styles.sectionEditor}>
          {activeSection === 'career_intent' ? (
            <>
              <div className={styles.sectionTitle}>求职意向</div>
              <label className={styles.fieldLabel}>目标岗位</label>
              <Input
                value={targetRoles}
                onChange={(e) => setTargetRoles(e.target.value)}
                placeholder="Backend Engineer, Platform Engineer"
              />
              <div className={styles.inlineExample}>例子：Backend Engineer, Platform Engineer</div>
              <label className={styles.fieldLabel}>目标城市</label>
              <Input
                value={targetLocations}
                onChange={(e) => setTargetLocations(e.target.value)}
                placeholder="Shanghai, Remote"
              />
              <div className={styles.inlineExample}>例子：Shanghai, Remote</div>
            </>
          ) : currentMeta ? (
            <>
              <div className={styles.sectionTitle}>{currentMeta.label}</div>
              <Input.TextArea
                value={drafts[currentMeta.key]}
                onChange={(e) => handleDraftChange(currentMeta.key, e.target.value)}
                rows={currentMeta.mode === 'text' ? 12 : 14}
                placeholder={currentMeta.placeholder}
                className={currentMeta.mode === 'json' ? styles.codeTextarea : undefined}
              />
              <div className={styles.inlineExample}>例子：{currentMeta.example}</div>
            </>
          ) : null}
        </section>
      </div>
    </section>
  );
}

function normalizeContent(content: ResumeContent | unknown): ResumeContent {
  return content && typeof content === 'object' && !Array.isArray(content) ? (content as ResumeContent) : {};
}

function normalizeCareerIntent(intent: ResumeContent['career_intent']): CareerIntent {
  return intent && typeof intent === 'object' && !Array.isArray(intent) ? intent : {};
}

function stringifyDraft(value: unknown): string {
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function buildContent({
  targetRoles,
  targetLocations,
  drafts,
}: {
  targetRoles: string;
  targetLocations: string;
  drafts: Record<SectionKey, string>;
}): ResumeContent {
  const content: Record<string, unknown> = {
    career_intent: {
      target_roles: splitList(targetRoles),
      target_locations: splitList(targetLocations),
    },
  };

  for (const meta of SECTION_META) {
    const draft = drafts[meta.key] ?? '';
    if (meta.mode === 'text') {
      content[meta.key] = draft;
      continue;
    }
    try {
      content[meta.key] = draft.trim() ? JSON.parse(draft) : sectionDefault(meta.key);
    } catch {
      throw new Error(`${meta.label} 需要是合法 JSON`);
    }
  }

  return content as ResumeContent;
}

function sectionDefault(key: SectionKey) {
  if (key === 'contact') return {};
  if (key === 'raw_text') return '';
  return [];
}

function splitList(value: string): string[] {
  return value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}
