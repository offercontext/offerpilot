import { PaperClipOutlined } from '@ant-design/icons';
import type { DragEvent } from 'react';
import type { PilotContextAttachment } from '@/types/chat';

export const NATIVE_PILOT_ATTACHMENT_TYPE = 'application/x-offerpilot-context-attachment';

interface PilotAttachmentHandleProps {
  attachment: PilotContextAttachment;
  onAttach: (attachment: PilotContextAttachment) => void;
  className?: string;
}

export default function PilotAttachmentHandle({
  attachment,
  onAttach,
  className,
}: PilotAttachmentHandleProps) {
  const handleDragStart = (event: DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.setData(NATIVE_PILOT_ATTACHMENT_TYPE, JSON.stringify(attachment));
    event.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <button
      type="button"
      className={className}
      draggable
      aria-label={`添加 ${attachment.label} 到 Pilot 上下文`}
      title="添加到 Pilot 上下文"
      onDragStart={handleDragStart}
      onClick={() => onAttach(attachment)}
    >
      <PaperClipOutlined aria-hidden="true" />
      添加到 Pilot
    </button>
  );
}
