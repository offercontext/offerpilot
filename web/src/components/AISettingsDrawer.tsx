import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ApiOutlined,
  CheckCircleOutlined,
  KeyOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  getSettings,
  SETTINGS_QUERY_KEY,
  updateSettings,
  type Settings,
  type UpdateSettingsPayload,
} from '@/services/chat';

interface Props {
  open: boolean;
  onClose: () => void;
}

interface FormValues {
  api_key?: string;
  provider: string;
  base_url: string;
  model: string;
  chat_auto_approve_writes: boolean;
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  openai_compatible: 'OpenAI 兼容',
  anthropic: 'Anthropic',
  openrouter: 'OpenRouter',
};

function activeProvider(settings?: Settings) {
  return settings?.providers?.find((item) => item.id === settings.active_provider_id);
}

function toFormValues(settings?: Settings): FormValues {
  const provider = activeProvider(settings);
  return {
    api_key: '',
    provider: provider?.provider || 'openai',
    base_url: settings?.base_url || 'https://api.openai.com/v1',
    model: settings?.model || 'gpt-4o',
    chat_auto_approve_writes: settings?.chat_auto_approve_writes ?? false,
  };
}

export default function AISettingsDrawer({ open, onClose }: Props) {
  const [form] = Form.useForm<FormValues>();
  const qc = useQueryClient();

  const settingsQuery = useQuery({
    queryKey: SETTINGS_QUERY_KEY,
    queryFn: getSettings,
    enabled: open,
  });

  useEffect(() => {
    if (open) {
      form.setFieldsValue(toFormValues(settingsQuery.data));
    }
  }, [form, open, settingsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) => {
      const providerId = settingsQuery.data?.active_provider_id || 'default';
      const providerLabel = PROVIDER_LABELS[values.provider] || values.provider;
      const payload: UpdateSettingsPayload = {
        chat_auto_approve_writes: values.chat_auto_approve_writes,
        active_provider_id: providerId,
        base_url: values.base_url,
        model: values.model,
        providers: [
          {
            id: providerId,
            label: providerLabel,
            provider: values.provider,
            base_url: values.base_url,
            model: values.model,
            enabled: true,
          },
        ],
      };
      const apiKey = values.api_key?.trim();
      if (apiKey) {
        payload.api_key = apiKey;
        payload.providers![0].api_key = apiKey;
      }
      return updateSettings(payload);
    },
    onSuccess: (settings) => {
      qc.setQueryData(SETTINGS_QUERY_KEY, settings);
      qc.invalidateQueries({ queryKey: SETTINGS_QUERY_KEY });
      message.success('AI 设置已保存');
      form.setFieldValue('api_key', '');
      onClose();
    },
    onError: () => {
      message.error('AI 设置保存失败');
    },
  });

  const hasKey = settingsQuery.data?.has_api_key ?? false;

  return (
    <Drawer
      title={
        <Space>
          <ApiOutlined />
          AI 设置
        </Space>
      }
      open={open}
      onClose={onClose}
      width={440}
      destroyOnClose
      extra={
        <Button type="primary" loading={saveMutation.isPending} onClick={() => form.submit()}>
          保存
        </Button>
      }
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          type={hasKey ? 'success' : 'warning'}
          showIcon
          icon={hasKey ? <CheckCircleOutlined /> : <WarningOutlined />}
          message={hasKey ? '密钥已配置' : '尚未配置密钥'}
          description={hasKey ? '密钥留空保存会保留当前密钥。' : '配置模型供应商密钥后即可使用 AI 能力。'}
        />

        <Form<FormValues>
          form={form}
          layout="vertical"
          initialValues={toFormValues(settingsQuery.data)}
          onFinish={(values) => saveMutation.mutate(values)}
        >
          <Form.Item label="API 密钥" name="api_key">
            <Input.Password
              prefix={<KeyOutlined />}
              autoComplete="off"
              placeholder={hasKey ? '留空则保留当前密钥' : 'sk-...'}
            />
          </Form.Item>

          <Form.Item label="模型供应商" name="provider">
            <Select
              options={[
                { value: 'openai', label: 'OpenAI' },
                { value: 'openai_compatible', label: 'OpenAI 兼容' },
                { value: 'anthropic', label: 'Anthropic' },
                { value: 'openrouter', label: 'OpenRouter' },
              ]}
            />
          </Form.Item>

          <Form.Item label="接口地址" name="base_url" tooltip="OpenAI 兼容接口地址">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item label="模型" name="model">
            <Input placeholder="gpt-4o" />
          </Form.Item>

          <Form.Item label="写操作自动确认" name="chat_auto_approve_writes" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            设置保存在本地 OfferPilot 配置中；接口只返回密钥是否存在。
          </Typography.Paragraph>

          <div style={{ marginTop: 14 }}>
            <Tag color="blue">LiteLLM</Tag>
            <Tag color="default">本地配置</Tag>
          </div>
        </Form>
      </Space>
    </Drawer>
  );
}
