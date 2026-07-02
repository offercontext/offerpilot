import { Button, Popconfirm } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Conversation } from '@/types/chat';
import styles from './ChatPanel.module.css';

interface Props {
  conversations: Conversation[];
  activeId?: number;
  onSelect: (id: number) => void;
  onNew: () => void;
  onDelete: (id: number) => void;
}

function modeLabel(mode?: string): string {
  return mode === 'nego_coach' ? '谈薪教练' : '通用';
}

export default function ThreadRail({ conversations, activeId, onSelect, onNew, onDelete }: Props) {
  return (
    <aside className={styles.rail}>
      <Button className={styles.railNew} block icon={<PlusOutlined />} onClick={onNew}>
        新建对话
      </Button>
      {conversations.length === 0 ? (
        <div className={styles.railEmpty}>暂无对话</div>
      ) : (
        <>
          <div className={styles.railLabel}>历史对话</div>
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`${styles.thread} ${c.id === activeId ? styles.threadActive : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(c.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSelect(c.id);
              }}
            >
              <div className={styles.threadMain}>
                <div className={styles.threadTitle}>{c.title}</div>
                <div className={styles.threadMeta}>
                  {modeLabel(c.mode)} · {dayjs(c.updated_at).format('M月D日')}
                </div>
              </div>
              <Popconfirm
                title="删除该对话？"
                okText="删除"
                cancelText="取消"
                onConfirm={(e) => {
                  e?.stopPropagation();
                  onDelete(c.id);
                }}
                onCancel={(e) => e?.stopPropagation()}
              >
                <DeleteOutlined
                  className={styles.threadDel}
                  aria-label="删除对话"
                  onClick={(e) => e.stopPropagation()}
                />
              </Popconfirm>
            </div>
          ))}
        </>
      )}
    </aside>
  );
}
