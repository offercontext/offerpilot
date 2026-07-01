import { useEffect, useState } from 'react';
import { Button, Modal, Upload } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload/interface';

interface Props {
  open: boolean;
  uploading?: boolean;
  onSubmit: (file: File) => void;
  onClose: () => void;
}

export default function KnowledgeImportModal({
  open,
  uploading = false,
  onSubmit,
  onClose,
}: Props) {
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    if (!open) {
      setFile(null);
    }
  }, [open]);

  const fileList: UploadFile[] = file
    ? [{ uid: file.name, name: file.name, status: 'done', size: file.size }]
    : [];

  return (
    <Modal
      title="导入知识文档"
      open={open}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button
          key="submit"
          type="primary"
          loading={uploading}
          disabled={!file}
          onClick={() => {
            if (file) onSubmit(file);
          }}
        >
          导入
        </Button>,
      ]}
    >
      <Upload.Dragger
        accept=".md,.txt"
        multiple={false}
        maxCount={1}
        fileList={fileList}
        beforeUpload={(nextFile) => {
          setFile(nextFile);
          return false;
        }}
        onRemove={() => {
          setFile(null);
          return true;
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">将 Markdown 或文本文件拖到这里</p>
        <p className="ant-upload-hint">仅支持 .md 和 .txt 文件。</p>
      </Upload.Dragger>
    </Modal>
  );
}
