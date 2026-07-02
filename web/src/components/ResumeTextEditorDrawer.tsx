import { useEffect, useState } from 'react';
import { Button, Descriptions, Drawer, Input, Space, message } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateResumeText, downloadResumeFile } from '@/services/resumes';
import type { Resume } from '@/types/resume';
import dayjs from 'dayjs';

interface Props {
  resume: Resume | null;
  open: boolean;
  onClose: () => void;
}

export default function ResumeTextEditorDrawer({ resume, open, onClose }: Props) {
  const qc = useQueryClient();
  const [text, setText] = useState('');

  useEffect(() => {
    setText(resume?.parsed_data ?? '');
  }, [resume?.parsed_data, resume?.id, open]);

  const saveMut = useMutation({
    mutationFn: () => updateResumeText(resume!.id, text),
    onSuccess: () => {
      message.success('已保存');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      onClose();
    },
    onError: () => message.error('保存失败'),
  });

  if (!resume && open) return null;

  const handleDownload = async () => {
    if (!resume) return;
    try {
      const blob = await downloadResumeFile(resume.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${resume.name || 'resume'}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error('下载失败');
    }
  };

  return (
    <Drawer
      title="校正简历文本"
      open={open}
      onClose={onClose}
      width={560}
      destroyOnClose
      footer={
        <Space style={{ float: 'right' }}>
          {resume?.file_path && (
            <Button onClick={handleDownload} icon={<span>⬇</span>}>
              下载原文件
            </Button>
          )}
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            loading={saveMut.isPending}
            disabled={!text.trim()}
            onClick={() => saveMut.mutate()}
          >
            保存
          </Button>
        </Space>
      }
    >
      <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="名称">{resume?.name || `简历 #${resume?.id}`}</Descriptions.Item>
        <Descriptions.Item label="创建时间">
          {resume ? dayjs(resume.created_at).format('YYYY-MM-DD HH:mm') : ''}
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          {resume?.parse_status === 'text-ready' ? '文本就绪' : '解析失败'}
        </Descriptions.Item>
      </Descriptions>
      <Input.TextArea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={18}
        placeholder="提取的简历文本（可校正）"
        style={{ fontFamily: 'inherit' }}
      />
    </Drawer>
  );
}