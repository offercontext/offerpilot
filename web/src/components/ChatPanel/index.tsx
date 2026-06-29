import { useEffect, useRef, useState } from 'react';
import { Drawer, Input, Button, Switch, Space, Typography, App as AntApp } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import {
  sendChat,
  confirmAction,
  getSettings,
  updateAutoApprove,
} from '@/services/chat';
import type { ChatResponse, PendingAction } from '@/types/chat';
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
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    getSettings()
      .then((s) => {
        setAutoApprove(s.chat_auto_approve_writes);
        setHasKey(s.has_api_key);
      })
      .catch(() => undefined);
  }, [open]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, pending]);

  function applyResponse(resp: ChatResponse) {
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
    <Drawer title="AI 助手" placement="right" width={460} open={open} onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
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
                {m.role === 'assistant' ? <ReactMarkdown>{m.content}</ReactMarkdown> : m.content}
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
    </Drawer>
  );
}
