import { useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Select, message, Popconfirm, Button } from 'antd';
import { DeleteOutlined, RightOutlined, RobotOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { deleteApplication } from '@/services/applications';
import { STATUS_LABELS } from '@/types/application';
import type { Application, ApplicationStatus } from '@/types/application';
import { createPilotAttachmentDragBinding } from '../PilotAttachmentHandle';
import styles from './KanbanBoard.module.css';

const STATUS_OPTIONS = (Object.entries(STATUS_LABELS) as [ApplicationStatus, string][]).map(
  ([value, label]) => ({ value, label })
);

interface KanbanCardProps {
  record: Application;
  columnStatus?: ApplicationStatus;
  isDragging?: boolean;
  overlay?: boolean;
  onOpenDetail?: (app: Application) => void;
  onAskPilot?: (app: Application) => void;
  onAttachToPilot?: (attachment: import('@/types/chat').PilotContextAttachment) => void;
  onRequestStatusChange?: (app: Application, status: ApplicationStatus) => void;
}

export default function KanbanCard({
  record,
  columnStatus,
  isDragging,
  overlay,
  onOpenDetail,
  onAskPilot,
  onAttachToPilot,
  onRequestStatusChange,
}: KanbanCardProps) {
  const queryClient = useQueryClient();
  const [selectOpen, setSelectOpen] = useState(false);

  const { attributes, listeners, setNodeRef } = useDraggable({
    id: record.id,
    data: { status: columnStatus },
    disabled: overlay,
  });
  const applicationDragBinding = onAttachToPilot
    ? createPilotAttachmentDragBinding({
        kind: 'application',
        id: String(record.id),
        label: `${record.company_name} · ${record.position_name}`,
      })
    : undefined;

  const handleStatusChange = async (newStatus: ApplicationStatus) => {
    if (newStatus === record.status) return;
    onRequestStatusChange?.(record, newStatus);
  };

  const handleDelete = async () => {
    try {
      await deleteApplication(record.id);
      queryClient.invalidateQueries({ queryKey: ['applications'] });
      queryClient.invalidateQueries({ queryKey: ['events'] });
      message.success('已删除');
    } catch {
      message.error('删除失败');
    }
  };

  const cardContent = (
    <>
      <div className={styles.cardCompany}>{record.company_name}</div>
      <div className={styles.cardName}>{record.position_name}</div>
      <div className={styles.cardDate}>{dayjs(record.applied_at).format('YYYY-MM-DD')}</div>
      {record.notes && <div className={styles.cardNotes}>{record.notes}</div>}
    </>
  );

  // DragOverlay renders the floating card during drag.
  if (overlay) {
    return <div className={`${styles.card} ${styles.cardOverlay}`}>{cardContent}</div>;
  }

  return (
    <div
      ref={setNodeRef}
      className={`${styles.card} ${isDragging ? styles.cardPlaceholder : ''}`}
      {...applicationDragBinding}
    >
      <div className={styles.cardDragSurface} {...listeners} {...attributes}>
        {cardContent}
      </div>
      <div className={styles.cardFooter}>
        <Select
          value={record.status}
          options={STATUS_OPTIONS}
          onChange={handleStatusChange}
          open={selectOpen}
          onDropdownVisibleChange={setSelectOpen}
          size="small"
          popupMatchSelectWidth={false}
          style={{ minWidth: 90 }}
          onClick={(e) => e.stopPropagation()}
        />
        <span style={{ display: 'flex', alignItems: 'center' }}>
          {onOpenDetail && (
            <Button
              type="text"
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                onOpenDetail(record);
              }}
              style={{ color: '#0284c7', marginLeft: 4, padding: '0 4px' }}
              title="查看详情"
            >
              <RightOutlined />
            </Button>
          )}
          {onAskPilot && (
            <Button
              type="text"
              size="small"
              icon={<RobotOutlined />}
              onClick={(e) => {
                e.stopPropagation();
                onAskPilot(record);
              }}
              style={{ color: '#0284c7', padding: '0 4px' }}
            >
              问 Pilot
            </Button>
          )}
          <Popconfirm
            title="确定删除这条投递？"
            onConfirm={handleDelete}
            okText="删除"
            cancelText="取消"
          >
            <DeleteOutlined
              style={{ color: '#94a3b8', marginLeft: 8, cursor: 'pointer' }}
              onClick={(e) => e.stopPropagation()}
            />
          </Popconfirm>
        </span>
      </div>
    </div>
  );
}
