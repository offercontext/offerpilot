import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
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
  type FormInstance,
} from 'antd';
import {
  ApiOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  KeyOutlined,
  PlusOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  getSettings,
  SETTINGS_QUERY_KEY,
  testProviderConnection,
  updateSettings,
  type ProviderTestPayload,
  type ProviderTestResult,
  type Settings,
  type UpdateSettingsPayload,
} from '@/services/chat';

interface Props {
  open: boolean;
  onClose: () => void;
}

interface ProviderFormValue {
  id: string;
  label: string;
  provider: string;
  api_key?: string;
  base_url: string;
  model: string;
  enabled: boolean;
}

interface FormValues {
  chat_auto_approve_writes: boolean;
  active_provider_id: string;
  fallback_provider_ids: string[];
  providers: ProviderFormValue[];
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  openai_compatible: 'OpenAI 兼容',
  anthropic: 'Anthropic',
  openrouter: 'OpenRouter',
};

function createDefaultProvider(index = 1): ProviderFormValue {
  return {
    id: `provider-${Date.now()}-${index}`,
    label: `Provider ${index}`,
    provider: 'openai',
    api_key: '',
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    enabled: true,
  };
}

function toFormValues(settings?: Settings): FormValues {
  const providers =
    settings?.providers?.map((provider) => ({
      id: provider.id,
      label: provider.label,
      provider: provider.provider,
      api_key: '',
      base_url: provider.base_url,
      model: provider.model,
      enabled: provider.enabled,
    })) ?? [];
  const firstProvider = providers[0] ?? createDefaultProvider();
  return {
    chat_auto_approve_writes: settings?.chat_auto_approve_writes ?? false,
    active_provider_id: settings?.active_provider_id || firstProvider.id,
    fallback_provider_ids: settings?.fallback_provider_ids ?? [],
    providers: providers.length ? providers : [firstProvider],
  };
}

function toPayload(values: FormValues): UpdateSettingsPayload {
  const providers = values.providers.length ? values.providers : [createDefaultProvider()];
  const active = providers.find((provider) => provider.id === values.active_provider_id) ?? providers[0];
  return {
    chat_auto_approve_writes: values.chat_auto_approve_writes,
    active_provider_id: active.id,
    fallback_provider_ids: values.fallback_provider_ids ?? [],
    base_url: active.base_url,
    model: active.model,
    providers: providers.map((provider) => ({
      id: provider.id,
      label: provider.label || PROVIDER_LABELS[provider.provider] || provider.provider,
      provider: provider.provider,
      api_key: provider.api_key?.trim() || undefined,
      base_url: provider.base_url,
      model: provider.model,
      enabled: provider.enabled,
    })),
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
    mutationFn: (values: FormValues) => updateSettings(toPayload(values)),
    onSuccess: (settings) => {
      qc.setQueryData(SETTINGS_QUERY_KEY, settings);
      qc.invalidateQueries({ queryKey: SETTINGS_QUERY_KEY });
      message.success('AI 设置已保存');
      form.setFieldsValue(toFormValues(settings));
      onClose();
    },
    onError: () => {
      message.error('AI 设置保存失败');
    },
  });

  const testMutation = useMutation({
    mutationFn: testProviderConnection,
    onSuccess: (result) => {
      if (result.ok) {
        message.success(`连接成功：${result.latency_ms}ms`);
      } else {
        message.error(`连接失败：${result.error || '未知错误'}`);
      }
    },
    onError: () => {
      message.error('连接测试失败');
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
      width={720}
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
          <ProviderList form={form} testMutation={testMutation} />

          <Form.Item label="写操作自动确认" name="chat_auto_approve_writes" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            设置保存在本地 OfferPilot 配置中；接口只返回密钥是否存在。备用顺序会在默认供应商失败时依次尝试。
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

function ProviderList({
  form,
  testMutation,
}: {
  form: FormInstance<FormValues>;
  testMutation: UseMutationResult<ProviderTestResult, Error, ProviderTestPayload>;
}) {
  const providers = Form.useWatch('providers', form) ?? [];
  const activeProviderId = Form.useWatch('active_provider_id', form);
  const fallbackOptions = providers
    .filter((provider) => provider.id && provider.id !== activeProviderId)
    .map((provider) => ({ value: provider.id, label: provider.label || provider.id }));

  return (
    <>
      <Form.Item label="默认供应商" name="active_provider_id">
        <Select options={providers.map((provider) => ({ value: provider.id, label: provider.label || provider.id }))} />
      </Form.Item>

      <Form.Item label="备用顺序" name="fallback_provider_ids">
        <Select mode="multiple" options={fallbackOptions} placeholder="默认供应商失败时按顺序尝试" />
      </Form.Item>

      <Form.List name="providers">
        {(fields, { add, remove }) => (
          <div style={{ display: 'grid', gap: 12 }}>
            {fields.map((field, index) => (
              <section key={field.key} style={providerPanelStyle}>
                <Space align="start" wrap style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Typography.Text strong>ProviderList #{index + 1}</Typography.Text>
                  <Space wrap>
                    <Button
                      size="small"
                      onClick={() => {
                        const provider = form.getFieldValue(['providers', field.name]) as ProviderFormValue;
                        form.setFieldValue('active_provider_id', provider.id);
                      }}
                    >
                      设为默认
                    </Button>
                    <Button
                      size="small"
                      loading={testMutation.isPending}
                      onClick={() => {
                        const provider = form.getFieldValue(['providers', field.name]) as ProviderFormValue;
                        testMutation.mutate({ provider });
                      }}
                    >
                      测试连接
                    </Button>
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={fields.length <= 1}
                      onClick={() => remove(field.name)}
                    />
                  </Space>
                </Space>

                <div style={providerGridStyle}>
                  <Form.Item label="ID" name={[field.name, 'id']} rules={[{ required: true, message: '请输入 ID' }]}>
                    <Input placeholder="openai" />
                  </Form.Item>
                  <Form.Item label="名称" name={[field.name, 'label']} rules={[{ required: true, message: '请输入名称' }]}>
                    <Input placeholder="OpenAI" />
                  </Form.Item>
                  <Form.Item label="模型供应商" name={[field.name, 'provider']}>
                    <Select
                      options={[
                        { value: 'openai', label: 'OpenAI' },
                        { value: 'openai_compatible', label: 'OpenAI 兼容' },
                        { value: 'anthropic', label: 'Anthropic' },
                        { value: 'openrouter', label: 'OpenRouter' },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item label="模型" name={[field.name, 'model']} rules={[{ required: true, message: '请输入模型' }]}>
                    <Input placeholder="gpt-4o" />
                  </Form.Item>
                  <Form.Item label="接口地址" name={[field.name, 'base_url']}>
                    <Input placeholder="https://api.openai.com/v1" />
                  </Form.Item>
                  <Form.Item label="API 密钥" name={[field.name, 'api_key']}>
                    <Input.Password
                      prefix={<KeyOutlined />}
                      autoComplete="off"
                      placeholder="留空则保留当前密钥"
                    />
                  </Form.Item>
                  <Form.Item label="启用" name={[field.name, 'enabled']} valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </div>
              </section>
            ))}
            <Button
              icon={<PlusOutlined />}
              onClick={() => add(createDefaultProvider(fields.length + 1))}
              block
            >
              新增供应商
            </Button>
          </div>
        )}
      </Form.List>
    </>
  );
}

const providerPanelStyle = {
  display: 'grid',
  gap: 12,
  padding: 12,
  border: '1px solid var(--op-border)',
  borderRadius: 8,
  background: 'rgba(148, 163, 184, 0.06)',
} as const;

const providerGridStyle = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
  columnGap: 12,
} as const;
