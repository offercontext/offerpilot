import { Button, Popconfirm } from 'antd';
import { PlusOutlined, DeleteOutlined, PushpinOutlined, EditOutlined, InboxOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Conversation } from '@/types/chat';
import type { UpdateConversationPayload } from '@/services/chat';
import styles from './ChatPanel.module.css';

interface Props {
  conversations: Conversation[];
  activeId?: number;
  onSelect: (id: number) => void;
  onNew: () => void;
  onDelete: (id: number) => void;
  onUpdate: (id: number, payload: UpdateConversationPayload) => void;
}

function modeLabel(mode?: string): string {
  return mode === 'nego_coach' ? '谈薪教练' : '通用';
}

export default function ThreadRail({ conversations, activeId, onSelect, onNew, onDelete, onUpdate }: Props) {
  function renameConversation(conversation: Conversation) {
    const title = window.prompt('重命名对话', conversation.title)?.trim();
    if (!title || title === conversation.title) return;
    onUpdate(conversation.id, { title });
  }

  function stopActionPropagation(e: React.SyntheticEvent) {
    e.stopPropagation();
  }

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
                if (e.target !== e.currentTarget) return;
                if (e.key === 'Enter') onSelect(c.id);
              }}
            >
              <div className={styles.threadMain}>
                <div className={styles.threadTitle}>{c.title}</div>
                <div className={styles.threadMeta}>
                  {modeLabel(c.mode)} · {dayjs(c.updated_at).format('M月D日')}
                </div>
              </div>
              <div className={styles.threadActions}>
                <Button
                  type="text"
                  size="small"
                  className={styles.threadAction}
                  aria-label={c.pinned_at ? '取消置顶对话' : '置顶对话'}
                  title={c.pinned_at ? '取消置顶' : '置顶'}
                  icon={<PushpinOutlined />}
                  onKeyDown={stopActionPropagation}
                  onClick={(e) => {
                    e.stopPropagation();
                    onUpdate(c.id, { pinned: !c.pinned_at });
                  }}
                />
                <Button
                  type="text"
                  size="small"
                  className={styles.threadAction}
                  aria-label="重命名对话"
                  title="重命名"
                  icon={<EditOutlined />}
                  onKeyDown={stopActionPropagation}
                  onClick={(e) => {
                    e.stopPropagation();
                    renameConversation(c);
                  }}
                />
                <Button
                  type="text"
                  size="small"
                  className={styles.threadAction}
                  aria-label="归档对话"
                  title="归档"
                  icon={<InboxOutlined />}
                  onKeyDown={stopActionPropagation}
                  onClick={(e) => {
                    e.stopPropagation();
                    onUpdate(c.id, { archived: true });
                  }}
                />
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
                    className={styles.threadAction}
                    aria-label="删除对话"
                    onKeyDown={stopActionPropagation}
                    onClick={(e) => e.stopPropagation()}
                  />
                </Popconfirm>
              </div>
            </div>
          ))}
        </>
      )}
    </aside>
  );
}
