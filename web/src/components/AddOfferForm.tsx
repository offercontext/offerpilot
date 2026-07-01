import { useEffect } from 'react';
import { Modal, Form, Input, InputNumber, Select, App as AntApp } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { Application } from '@/types/application';
import type { Offer, OfferInput, OfferStatus } from '@/types/offer';
import { OFFER_STATUS_LABELS } from '@/types/offer';
import { createOffer, updateOffer } from '@/services/offers';

interface Props {
  open: boolean;
  onClose: () => void;
  applications: Application[];
  editing?: Offer | null;
}

const STATUS_OPTIONS = (Object.keys(OFFER_STATUS_LABELS) as OfferStatus[]).map((s) => ({
  value: s,
  label: OFFER_STATUS_LABELS[s],
}));

export default function AddOfferForm({ open, onClose, applications, editing }: Props) {
  const [form] = Form.useForm();
  const { message: toast } = AntApp.useApp();
  const qc = useQueryClient();

  useEffect(() => {
    if (open) {
      if (editing) {
        form.setFieldsValue(editing);
      } else {
        form.resetFields();
        form.setFieldsValue({ months_per_year: 12, status: 'pending' });
      }
    }
  }, [open, editing, form]);

  const mutation = useMutation({
    mutationFn: async (values: OfferInput) => {
      if (editing) return updateOffer(editing.id, values);
      return createOffer(values);
    },
    onSuccess: () => {
      toast.success(editing ? 'Offer 已更新' : 'Offer 已录入');
      qc.invalidateQueries({ queryKey: ['offers'] });
      onClose();
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { error?: string } } })?.response?.data?.error;
      toast.error(msg || '保存失败');
    },
  });

  return (
    <Modal
      title={editing ? '编辑 Offer' : '录入 Offer'}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={mutation.isPending}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={(v) => mutation.mutate(v as OfferInput)}>
        <Form.Item name="company_name" label="公司" rules={[{ required: true, message: '请输入公司' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="position_name" label="岗位" rules={[{ required: true, message: '请输入岗位' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="application_id" label="关联投递（可选）">
          <Select
            allowClear
            placeholder="选择投递记录"
            options={applications.map((a) => ({ value: a.id, label: `#${a.id} ${a.company_name} - ${a.position_name}` }))}
          />
        </Form.Item>
        <Form.Item name="status" label="状态">
          <Select options={STATUS_OPTIONS} />
        </Form.Item>
        <Form.Item name="base_monthly" label="月薪（元）" rules={[{ type: 'number', min: 0, message: '不能为负' }]}>
          <InputNumber style={{ width: '100%' }} min={0} />
        </Form.Item>
        <Form.Item name="months_per_year" label="薪数（如 12/13/16）" rules={[{ type: 'number', min: 1, message: '至少 1' }]}>
          <InputNumber style={{ width: '100%' }} min={1} />
        </Form.Item>
        <Form.Item name="signing_bonus" label="签字费（元）">
          <InputNumber style={{ width: '100%' }} min={0} />
        </Form.Item>
        <Form.Item name="equity" label="期权">
          <Input placeholder="如 20万股 RSU 4年 vest" />
        </Form.Item>
        <Form.Item name="perks" label="福利">
          <Input />
        </Form.Item>
        <Form.Item name="deadline" label="截止日">
          <Input placeholder="如 2026-07-08" />
        </Form.Item>
        <Form.Item name="notes" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
