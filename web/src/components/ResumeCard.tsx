import { Card, Tag, Tooltip } from 'antd';
import {
  DownloadOutlined,
  EditOutlined,
  RobotOutlined,
  DeleteOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type { ReactNode } from 'react';
import type { Resume } from '@/types/resume';

interface Props {
  resume: Resume;
  onMatch: (id: number) => void;
  onEdit: (id: number) => void;
  onDownload: (id: number) => void;
  onDelete: (id: number) => void;
}

export default function ResumeCard({ resume, onMatch, onEdit, onDownload, onDelete }: Props) {
  const failed = resume.parse_status === 'parse-failed';
  const summary = (resume.parsed_data || '').slice(0, 80).replace(/\s+/g, ' ').trim();
  return (
    <Card hoverable styles={{ body: { padding: 14 } }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Tag color={failed ? 'error' : 'gold'} style={{ borderRadius: 8 }}>PDF</Tag>
        <span style={{ fontSize: 11, color: 'var(--op-muted)' }}>
          {dayjs(resume.created_at).format('MM-DD HH:mm')}
        </span>
      </div>
      <div style={{ fontSize: 15, fontWeight: 600, margin: '10px 0 4px', color: 'var(--op-text)', textWrap: 'pretty' as const }}>
        {resume.name || `简历 #${resume.id}`}
      </div>
      <div style={{ fontSize: 12, color: 'var(--op-muted)', lineHeight: 1.5, height: 36, overflow: 'hidden', textWrap: 'pretty' as const }}>
        {failed ? (
          <span style={{ color: '#f87171' }}>
            <WarningOutlined /> 扫描版/图片式 PDF 无法提取文本，请手动校正
          </span>
        ) : (
          summary || '（无文本预览）'
        )}
      </div>
      <div style={{ display: 'flex', marginTop: 12, borderTop: '1px solid var(--op-border)', paddingTop: 10 }}>
        {failed ? (
          <>
            <CardAction label="手动校正" icon={<EditOutlined />} onClick={() => onEdit(resume.id)} primary />
            <VDivider />
            <CardAction label="删除" icon={<DeleteOutlined />} onClick={() => onDelete(resume.id)} />
          </>
        ) : (
          <>
            <CardAction label="匹配" icon={<RobotOutlined />} onClick={() => onMatch(resume.id)} primary />
            <VDivider />
            <CardAction label="编辑" icon={<EditOutlined />} onClick={() => onEdit(resume.id)} />
            <VDivider />
            <CardAction label="下载" icon={<DownloadOutlined />} onClick={() => onDownload(resume.id)} />
          </>
        )}
      </div>
    </Card>
  );
}

function VDivider() {
  return <span style={{ width: 1, background: 'var(--op-border)' }} />;
}

function CardAction({ label, icon, onClick, primary }: { label: string; icon: ReactNode; onClick: () => void; primary?: boolean }) {
  return (
    <Tooltip title={label}>
      <button
        onClick={onClick}
        aria-label={label}
        style={{
          flex: 1,
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: '4px 0',
          fontSize: 12,
          color: primary ? 'var(--op-primary)' : 'var(--op-muted)',
          fontWeight: primary ? 600 : 400,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 4,
        }}
      >
        {icon}
        <span>{label}</span>
      </button>
    </Tooltip>
  );
}