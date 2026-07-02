import { useRef, useState } from 'react';
import { Button, Input, Spin, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { DragEvent } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listResumes, uploadResume, deleteResume } from '@/services/resumes';
import ResumeCard from './ResumeCard';
import ResumeUploadModal from './ResumeUploadModal';
import ResumeTextEditorDrawer from './ResumeTextEditorDrawer';
import type { Resume } from '@/types/resume';
import styles from './ResumeLibraryView.module.css';

export default function ResumeLibraryView() {
  const qc = useQueryClient();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editing, setEditing] = useState<Resume | null>(null);
  const [keyword, setKeyword] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const dragCounter = useRef(0);

  const resumesQuery = useQuery({ queryKey: ['resumes'], queryFn: listResumes });

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadResume(file),
    onSuccess: (res) => {
      message.success(res.parse_status === 'text-ready' ? '上传成功' : '已上传，但文本提取失败，请手动校正');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      setUploadOpen(false);
      setEditing(res);
    },
    onError: () => message.error('上传失败'),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteResume(id),
    onSuccess: () => { message.success('已删除'); qc.invalidateQueries({ queryKey: ['resumes'] }); },
    onError: () => message.error('删除失败'),
  });

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    dragCounter.current = 0;
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadMut.mutate(file);
  };

  const filtered = (resumesQuery.data ?? []).filter((r) =>
    !keyword || (r.name || '').toLowerCase().includes(keyword.toLowerCase())
  );

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
        <div style={{ display: 'flex', gap: 8 }}>
          <Input.Search
            placeholder="搜索简历"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            allowClear
            style={{ width: 200 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>上传简历</Button>
        </div>
      </div>

      {resumesQuery.isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
      ) : filtered.length === 0 ? (
        <div className={styles.dropZone}>
          <div className={styles.dropIcon}>📄</div>
          <div className={styles.dropTitle}>拖拽 PDF 简历到此处</div>
          <div className={styles.dropHint}>或点击右上角「上传简历」· 单文件最大 10MB</div>
        </div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((r, i) => (
            <div key={r.id} className={styles.card} style={{ animationDelay: `${Math.min(i, 6) * 60}ms` }}>
              <ResumeCard
                resume={r}
                onMatch={() => message.info('请到 AI 匹配入口选此简历')}
                onEdit={() => setEditing(r)}
                onDownload={() => message.info('请在编辑抽屉内下载原文件')}
                onDelete={() => deleteMut.mutate(r.id)}
              />
            </div>
          ))}
        </div>
      )}

      {filtered.length > 0 && !resumesQuery.isLoading && (
        <div className={`${styles.dropZone} ${dragActive ? styles.dropZoneActive : ''}`} style={{ marginTop: 16 }}>
          <div className={styles.dropIcon}>📄</div>
          <div className={styles.dropTitle}>拖拽 PDF 到此处上传</div>
          <div className={styles.dropHint}>或点击「上传简历」按钮</div>
        </div>
      )}

      {dragActive && <div className={styles.overlay}>松开以上传 PDF 简历</div>}

      <ResumeUploadModal
        open={uploadOpen}
        uploading={uploadMut.isPending}
        onSubmit={(f) => uploadMut.mutate(f)}
        onClose={() => setUploadOpen(false)}
      />
      <ResumeTextEditorDrawer
        resume={editing}
        open={!!editing}
        onClose={() => setEditing(null)}
      />
    </div>
  );
}