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
      message.success('AI settings saved');
      form.setFieldValue('api_key', '');
      onClose();
    },
    onError: () => {
      message.error('Failed to save AI settings');
    },
  });

  const hasKey = settingsQuery.data?.has_api_key ?? false;

  return (
    <Drawer
      title={
        <Space>
          <ApiOutlined />
          AI settings
        </Space>
      }
      open={open}
      onClose={onClose}
      width={440}
      destroyOnClose
      extra={
        <Button type="primary" loading={saveMutation.isPending} onClick={() => form.submit()}>
          Save
        </Button>
      }
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          type={hasKey ? 'success' : 'warning'}
          showIcon
          icon={hasKey ? <CheckCircleOutlined /> : <WarningOutlined />}
          message={hasKey ? 'API key configured' : 'API key not configured'}
          description={
            hasKey
              ? 'Leave the API key field blank to keep the saved key.'
              : 'Add a provider API key to enable AI analysis, matching, generation, and assistant features.'
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
              placeholder={hasKey ? 'Leave blank to keep saved key' : 'sk-...'}
            />
          </Form.Item>

          <Form.Item
            label="Base URL"
            name="base_url"
            tooltip="OpenAI-compatible endpoint base URL"
          >
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item label="Model" name="model">
            <Input placeholder="gpt-4o" />
          </Form.Item>

          <Form.Item
            label="Write auto-approve"
            name="chat_auto_approve_writes"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            Settings are stored locally in OfferPilot config. The API key is never returned by the settings API.
          </Typography.Paragraph>

          <div style={{ marginTop: 14 }}>
            <Tag color="blue">OpenAI-compatible</Tag>
            <Tag color="default">Local config</Tag>
          </div>
        </Form>
      </Space>
    </Drawer>
  );
}
