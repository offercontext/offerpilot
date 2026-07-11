import { useEffect, useRef, useState } from 'react';
import { Button, Input, Spin, message } from 'antd';
import {
  CloudUploadOutlined,
  FileAddOutlined,
  FileTextOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import type { DragEvent } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  copyResume,
  createResume,
  createResumeFromSample,
  deleteResume,
  listResumes,
  updateResume,
  uploadResume,
} from '@/services/resumes';
import { ONBOARDING_QUERY_KEY } from '@/services/onboarding';
import ResumeCard from './ResumeCard';
import ResumeUploadModal from './ResumeUploadModal';
import ResumeEditorDrawer from './ResumeEditorDrawer';
import type { Resume, ResumeContent } from '@/types/resume';
import styles from './ResumeLibraryView.module.css';

const BLANK_RESUME_CONTENT: ResumeContent = {
  career_intent: { target_roles: [], target_locations: [] },
  contact: {},
  education: [],
  experience: [],
  projects: [],
  skills: [],
  raw_text: '',
};

interface ResumeLibraryViewProps {
  onAttachToPilot?: (attachment: import('@/types/chat').PilotContextAttachment) => void;
}

export default function ResumeLibraryView({ onAttachToPilot }: ResumeLibraryViewProps) {
  const qc = useQueryClient();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editing, setEditing] = useState<Resume | null>(null);
  const [keyword, setKeyword] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const dragCounter = useRef(0);

  const resumesQuery = useQuery({ queryKey: ['resumes'], queryFn: listResumes });

  const createDialogMut = useMutation({
    mutationFn: () =>
      createResume({
        title: 'Pilot 对话薄版简历',
        source: 'dialog',
        content_json: BLANK_RESUME_CONTENT,
        career_intent: BLANK_RESUME_CONTENT.career_intent,
      }),
    onSuccess: (res) => {
      message.success('已创建薄版简历');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      qc.invalidateQueries({ queryKey: ONBOARDING_QUERY_KEY });
      setEditing(res);
    },
    onError: () => message.error('创建失败'),
  });

  const sampleMut = useMutation({
    mutationFn: () => createResumeFromSample({ sample_id: 'backend' }),
    onSuccess: (res) => {
      message.success('已从样例创建');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      qc.invalidateQueries({ queryKey: ONBOARDING_QUERY_KEY });
      setEditing(res);
    },
    onError: () => message.error('创建样例失败'),
  });

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadResume(file),
    onSuccess: (res) => {
      message.success(res.parse_status === 'text-ready' ? '上传成功' : '已上传，但文本提取失败，请手动校正');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      qc.invalidateQueries({ queryKey: ONBOARDING_QUERY_KEY });
      setUploadOpen(false);
      setEditing(res);
    },
    onError: () => message.error('上传失败'),
  });

  const setMasterMut = useMutation({
    mutationFn: (id: number) => updateResume(id, { is_master: true }),
    onSuccess: (res) => {
      message.success('已设为主简历');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      qc.invalidateQueries({ queryKey: ONBOARDING_QUERY_KEY });
      setEditing(res);
    },
    onError: () => message.error('设置主简历失败'),
  });

  const copyMut = useMutation({
    mutationFn: (id: number) => copyResume(id),
    onSuccess: (res) => {
      message.success('已复制简历');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      setEditing(res);
    },
    onError: () => message.error('复制失败'),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteResume(id),
    onSuccess: () => {
      message.success('已删除');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      qc.invalidateQueries({ queryKey: ONBOARDING_QUERY_KEY });
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.error;
      message.error(detail === 'master resume cannot be deleted' ? '主简历不可删除' : '删除失败');
    },
  });

  const uploadFile = (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      message.error('仅支持 PDF 简历');
      return;
    }
    uploadMut.mutate(file);
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    dragCounter.current = 0;
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadFile(file);
  };

  const resumes = resumesQuery.data ?? [];
  const kw = keyword.trim().toLowerCase();
  const filtered = resumes.filter((r) => {
    if (!kw) return true;
    return [
      r.title,
      r.name,
      r.source,
      ...(r.missing_sections ?? []),
    ].join(' ').toLowerCase().includes(kw);
  });

  useEffect(() => {
    if (editing) {
      window.scrollTo({ top: 0, left: 0 });
    }
  }, [editing]);

  if (editing) {
    return (
      <ResumeEditorDrawer
        resume={editing}
        open={!!editing}
        onClose={() => setEditing(null)}
        onSaved={(next) => setEditing(next)}
      />
    );
  }

  return (
    <div
      onDragEnter={(e) => { e.preventDefault(); dragCounter.current++; setDragActive(true); }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => { dragCounter.current--; if (dragCounter.current <= 0) { setDragActive(false); dragCounter.current = 0; } }}
      onDrop={handleDrop}
    >
      <div className={styles.header}>
        <div>
          <div className={styles.title}>简历库</div>
          <div className={styles.subtitle}>共 {filtered.length} 份 · 拖入 PDF 至任意位置可上传</div>
        </div>
        <div className={styles.headerActions}>
          <Input.Search
            placeholder="搜索简历"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            allowClear
            style={{ width: 200 }}
          />
          <Button
            icon={<PlusOutlined />}
            loading={createDialogMut.isPending}
            onClick={() => createDialogMut.mutate()}
          >
            和 Pilot 创建薄版
          </Button>
          <Button icon={<CloudUploadOutlined />} onClick={() => setUploadOpen(true)}>上传 PDF</Button>
          <Button
            type="primary"
            icon={<FileAddOutlined />}
            loading={sampleMut.isPending}
            onClick={() => sampleMut.mutate()}
          >
            用样例开始
          </Button>
        </div>
      </div>

      {resumesQuery.isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
      ) : resumes.length === 0 ? (
        <div className={styles.emptyState}>
          <div className={styles.emptyIcon}><FileTextOutlined /></div>
          <div className={styles.emptyTitle}>还没有简历</div>
          <div className={styles.emptyHint}>选择一个入口开始，之后都可以在编辑器里补全结构化章节。</div>
          <div className={styles.emptyActions}>
            <button className={styles.emptyAction} type="button" onClick={() => createDialogMut.mutate()}>
              <div className={styles.emptyActionTitle}>和 Pilot 创建薄版</div>
              <div className={styles.emptyActionDesc}>先生成可编辑的空结构，再逐章补充。</div>
            </button>
            <button className={styles.emptyAction} type="button" onClick={() => setUploadOpen(true)}>
              <div className={styles.emptyActionTitle}>上传 PDF</div>
              <div className={styles.emptyActionDesc}>继续使用现有上传流程，仅支持 PDF。</div>
            </button>
            <button className={styles.emptyAction} type="button" onClick={() => sampleMut.mutate()}>
              <div className={styles.emptyActionTitle}>用样例开始</div>
              <div className={styles.emptyActionDesc}>默认创建后端工程师样例。</div>
            </button>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className={styles.dropZone}>
          <div className={styles.dropTitle}>没有匹配的简历</div>
          <div className={styles.dropHint}>换个关键词，或从右上角创建新简历。</div>
        </div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((r, i) => (
            <div key={r.id} className={styles.card} style={{ animationDelay: `${Math.min(i, 6) * 60}ms` }}>
              <ResumeCard
                resume={r}
                onEdit={() => setEditing(r)}
                onSetMaster={() => setMasterMut.mutate(r.id)}
                onCopy={() => copyMut.mutate(r.id)}
                onDelete={() => deleteMut.mutate(r.id)}
                onAttachToPilot={onAttachToPilot}
              />
            </div>
          ))}
        </div>
      )}

      {resumes.length > 0 && !resumesQuery.isLoading && (
        <div className={`${styles.dropZone} ${styles.dropZoneCompact} ${dragActive ? styles.dropZoneActive : ''}`} style={{ marginTop: 16 }}>
          <div className={styles.dropTitle}>拖拽 PDF 到此处上传</div>
          <div className={styles.dropHint}>或点击「上传 PDF」按钮</div>
        </div>
      )}

      {dragActive && <div className={styles.overlay}>松开以上传 PDF 简历</div>}

      <ResumeUploadModal
        open={uploadOpen}
        uploading={uploadMut.isPending}
        onSubmit={uploadFile}
        onClose={() => setUploadOpen(false)}
      />
    </div>
  );
}
