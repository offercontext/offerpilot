import { useEffect, useRef, useState } from 'react';
import { Drawer, Input, Button, Switch, Space, Typography, List, Popconfirm, App as AntApp } from 'antd';
import { SendOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  sendChat,
  confirmAction,
  getSettings,
  updateAutoApprove,
  listConversations,
  getConversation,
  deleteConversation,
} from '@/services/chat';
import type { ChatResponse, Conversation, PendingAction } from '@/types/chat';
import ConfirmCard from './ConfirmCard';
import styles from './ChatPanel.module.css';

const { Text } = Typography;

interface UIMessage {
  role: 'user' | 'assistant' | 'tool';
  content: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ChatPanel({ open, onClose }: Props) {
  const { message: toast } = AntApp.useApp();
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState('');
  const [convID, setConvID] = useState<number | undefined>(undefined);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [loading, setLoading] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
  const [hasKey, setHasKey] = useState(true);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  function refreshConversations() {
    listConversations()
      .then(setConversations)
      .catch(() => undefined);
  }

  useEffect(() => {
    if (!open) return;
    getSettings()
      .then((s) => {
        setAutoApprove(s.chat_auto_approve_writes);
        setHasKey(s.has_api_key);
      })
      .catch(() => undefined);
    refreshConversations();
  }, [open]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, pending]);

  function startNewChat() {
    setConvID(undefined);
    setMessages([]);
    setPending(null);
  }

  async function selectConversation(id: number) {
    if (id === convID) return;
    setLoading(true);
    try {
      const stored = await getConversation(id);
      // Show user turns and assistant turns that have visible text; skip
      // tool-result turns and pure tool-call assistant turns (empty content).
      const ui: UIMessage[] = stored
        .filter((m) => m.role === 'user' || (m.role === 'assistant' && m.content.trim() !== ''))
        .map((m) => ({ role: m.role as UIMessage['role'], content: m.content }));
      setConvID(id);
      setMessages(ui);
      setPending(null);
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '加载对话失败');
    } finally {
      setLoading(false);
    }
  }

  async function removeConversation(id: number) {
    try {
      await deleteConversation(id);
      if (id === convID) startNewChat();
      refreshConversations();
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '删除失败');
    }
  }

  function applyResponse(resp: ChatResponse) {
    const isNew = convID === undefined;
    setConvID(resp.conversation_id);
    if (resp.type === 'confirmation_required') {
      setPending(resp.pending_action);
    } else {
      setPending(null);
      setMessages((m) => [...m, { role: 'assistant', content: resp.message }]);
      if (resp.degraded) {
        toast.info('当前模型不支持工具调用，已切换为只读摘要模式');
      }
    }
    if (isNew) refreshConversations();
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;
    setMessages((m) => [...m, { role: 'user', content: text }]);
    setInput('');
    setLoading(true);
    try {
      const resp = await sendChat(text, convID);
      applyResponse(resp);
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '对话失败');
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm(approved: boolean) {
    if (!convID) return;
    setLoading(true);
    try {
      const resp = await confirmAction(convID, approved);
      applyResponse(resp);
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '确认失败');
    } finally {
      setLoading(false);
    }
  }

  async function toggleAutoApprove(value: boolean) {
    setAutoApprove(value);
    try {
      await updateAutoApprove(value);
    } catch {
      setAutoApprove(!value);
      toast.error('设置保存失败');
    }
  }

  return (
    <Drawer title="AI 助手" placement="right" width={680} open={open} onClose={onClose}>
      <div style={{ display: 'flex', height: '100%', gap: 12 }}>
        {/* conversation list */}
        <div className={styles.sidebar}>
          <Button block icon={<PlusOutlined />} onClick={startNewChat} style={{ marginBottom: 8 }}>
            新建对话
          </Button>
          <List
            size="small"
            dataSource={conversations}
            locale={{ emptyText: '暂无对话' }}
            renderItem={(c) => (
              <List.Item
                className={c.id === convID ? styles.convActive : styles.convItem}
                onClick={() => selectConversation(c.id)}
                actions={[
                  <Popconfirm
                    key="del"
                    title="删除该对话？"
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      removeConversation(c.id);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                  >
                    <DeleteOutlined onClick={(e) => e.stopPropagation()} style={{ color: '#94a3b8' }} />
                  </Popconfirm>,
                ]}
              >
                <Text ellipsis style={{ maxWidth: 130 }}>
                  {c.title}
                </Text>
              </List.Item>
            )}
          />
        </div>

        {/* chat area */}
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
          <Space style={{ marginBottom: 8 }}>
            <Text type="secondary">写操作免确认</Text>
            <Switch checked={autoApprove} onChange={toggleAutoApprove} />
          </Space>

          {!hasKey && (
            <Text type="warning" style={{ marginBottom: 8 }}>
              尚未配置 API key，请先运行 oc config --api-key sk-xxx。
            </Text>
          )}

          <div className={styles.messages} style={{ flex: 1, overflowY: 'auto' }}>
            {messages.map((m, i) => (
              <div key={i} className={`${styles.row} ${m.role === 'user' ? styles.rowUser : ''}`}>
              <div className={`${styles.bubble} ${m.role === 'user' ? styles.user : styles.assistant}`}>
                {m.role === 'assistant' ? (
                  <div className={styles.markdown}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                  </div>
                ) : (
                  m.content
                )}
              </div>
              </div>
            ))}
            {pending && (
              <ConfirmCard
                action={pending}
                loading={loading}
                onConfirm={() => handleConfirm(true)}
                onCancel={() => handleConfirm(false)}
              />
            )}
            <div ref={endRef} />
          </div>

          <div className={styles.inputBar}>
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="问问 AI 关于你的求职进度…"
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={loading || !!pending}
            />
            <Button type="primary" icon={<SendOutlined />} loading={loading} disabled={!!pending} onClick={handleSend} />
          </div>
        </div>
      </div>
    </Drawer>
  );
}
