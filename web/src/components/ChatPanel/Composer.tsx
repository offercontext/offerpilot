import { useMemo, useState } from 'react';
import { Input, Button } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import type { Capability } from './capabilities';
import SlashMenu from './SlashMenu';
import styles from './ChatPanel.module.css';

interface Props {
  capabilities: Capability[];
  disabled?: boolean;
  disabledReason?: string;
  placeholder?: string;
  onSend: (text: string) => void | boolean | Promise<void | boolean>;
}

export default function Composer({ capabilities, disabled, disabledReason, placeholder, onSend }: Props) {
  const [value, setValue] = useState('');
  const [sel, setSel] = useState(0);

  const slashQuery = value.startsWith('/') ? value.slice(1).trim().toLowerCase() : null;
  const menuOpen = slashQuery !== null && !disabled;

  const items = useMemo(() => {
    if (slashQuery === null) return [];
    if (!slashQuery) return capabilities;
    return capabilities.filter(
      (c) => c.label.toLowerCase().includes(slashQuery) || c.hint.toLowerCase().includes(slashQuery),
    );
  }, [slashQuery, capabilities]);

  async function pickCapability(cap: Capability) {
    const needsMore = /[：:]$/.test(cap.prompt.trim());
    if (needsMore) {
      setValue(cap.prompt);
      setSel(0);
      return;
    }

    const sent = await onSend(cap.prompt);
    if (sent !== false) {
      setValue('');
      setSel(0);
    }
  }

  async function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    const sent = await onSend(text);
    if (sent !== false) {
      setValue('');
      setSel(0);
    }
  }

  return (
    <div className={styles.composer}>
      {menuOpen && items.length > 0 && (
        <SlashMenu items={items} selected={sel} onSelect={pickCapability} onHover={setSel} />
      )}
      <div className={styles.composerBox}>
        <Input.TextArea
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setSel(0);
          }}
          onKeyDown={(e) => {
            if (menuOpen && items.length > 0) {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setSel((s) => (s + 1) % items.length);
                return;
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault();
                setSel((s) => (s - 1 + items.length) % items.length);
                return;
              }
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void pickCapability(items[sel]);
                return;
              }
              if (e.key === 'Escape') {
                e.preventDefault();
                setValue('');
                return;
              }
            }
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder={placeholder ?? '问问领航员，或输入 / 唤起能力'}
          autoSize={{ minRows: 1, maxRows: 4 }}
          variant="borderless"
          disabled={disabled}
        />
        <Button
          type="primary"
          className="op-ai-btn"
          icon={<SendOutlined />}
          disabled={disabled || !value.trim()}
          onClick={() => void submit()}
          aria-label="发送"
        />
      </div>
      <div className={styles.hint}>
        {disabledReason ? (
          <span>{disabledReason}</span>
        ) : (
          <span>
            输入 <kbd>/</kbd> 唤起能力 · <kbd>Enter</kbd> 发送 · <kbd>Shift+Enter</kbd> 换行
          </span>
        )}
      </div>
    </div>
  );
}
