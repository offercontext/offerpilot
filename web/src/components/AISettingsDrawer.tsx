import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Drawer,
  Form,
  Input,
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
  base_url: string;
  model: string;
  chat_auto_approve_writes: boolean;
}

function toFormValues(settings?: Settings): FormValues {
  return {
    api_key: '',
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
      const payload: UpdateSettingsPayload = {
        chat_auto_approve_writes: values.chat_auto_approve_writes,
        base_url: values.base_url,
        model: values.model,
      };
      const apiKey = values.api_key?.trim();
      if (apiKey) payload.api_key = apiKey;
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
          message={hasKey ? 'API key 已配置' : '尚未配置 API key'}
          description={
            hasKey
              ? 'API key 留空保存时会保留当前密钥。'
              : '配置供应商 API key 后，即可使用 AI 分析、匹配、生成和助手功能。'
          }
        />

        <Form<FormValues>
          form={form}
          layout="vertical"
          initialValues={toFormValues(settingsQuery.data)}
          onFinish={(values) => saveMutation.mutate(values)}
        >
          <Form.Item label="API key" name="api_key">
            <Input.Password
              prefix={<KeyOutlined />}
              autoComplete="off"
              placeholder={hasKey ? '留空则保留当前密钥' : 'sk-...'}
            />
          </Form.Item>

          <Form.Item
            label="接口地址 Base URL"
            name="base_url"
            tooltip="OpenAI 兼容接口的 Base URL"
          >
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item label="模型" name="model">
            <Input placeholder="gpt-4o" />
          </Form.Item>

          <Form.Item
            label="写操作免确认"
            name="chat_auto_approve_writes"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            设置会保存在本地 OfferPilot 配置中。设置接口只返回是否已配置密钥，不会返回 API key 明文。
          </Typography.Paragraph>

          <div style={{ marginTop: 14 }}>
            <Tag color="blue">OpenAI 兼容</Tag>
            <Tag color="default">本地配置</Tag>
          </div>
        </Form>
      </Space>
    </Drawer>
  );
}
