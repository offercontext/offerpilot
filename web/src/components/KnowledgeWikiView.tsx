import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Badge,
  Button,
  Empty,
  Input,
  List,
  Modal,
  Progress,
  Space,
  Spin,
  Switch,
  Tabs,
  Typography,
  Upload,
  message,
} from 'antd';
import type { UploadFile } from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  FormOutlined,
  InboxOutlined,
  PictureOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import {
  archiveKnowledgeSource,
  buildKnowledgeAssetContentUrl,
  buildKnowledgeSourceContentUrl,
  cancelKnowledgeJob,
  deleteKnowledgeSource,
  fetchKnowledgeSource,
  fetchKnowledgeSourceBrief,
  fetchKnowledgeSourceEvidence,
  fetchKnowledgeSourceJobs,
  fetchKnowledgeSources,
  pasteKnowledgeSource,
  rebuildKnowledgeSourceBrief,
  searchKnowledgeEvidence,
  unarchiveKnowledgeSource,
  updateKnowledgeSourceTitle,
  uploadKnowledgeBundle,
  uploadKnowledgeSource,
} from '@/services/knowledge';
import type {
  BriefStatement,
  KnowledgeBriefAttempt,
  KnowledgeEvidence,
  KnowledgeJob,
  KnowledgeSource,
  KnowledgeSourceBrief,
  KnowledgeSourceBriefResponse,
  KnowledgeSourceJobsResponse,
} from '@/types/knowledge';

const { Paragraph, Text, Title } = Typography;

const KNOWLEDGE_QUERY_KEY = ['knowledge', 'sources'] as const;

const STATUS_LABEL: Record<string, string> = {
  active: '活跃',
  archived: '已归档',
  deleting: '删除中',
};
const EXTRACTION_LABEL: Record<string, string> = {
  pending: '等待解析',
  processing: '解析中',
  extracted: '已解析',
  failed: '解析失败',
};
const BRIEF_LABEL: Record<string, string> = {
  not_started: '尚未生成',
  pending: '排队中',
  processing: '生成中',
  ready: '已生成',
  failed: '生成失败',
  outdated: '已过期',
};

export default function KnowledgeWikiView() {
  const queryClient = useQueryClient();
  const [includeArchived, setIncludeArchived] = useState(false);
  const sourcesQuery = useQuery({
    queryKey: KNOWLEDGE_QUERY_KEY,
    queryFn: () => fetchKnowledgeSources({ includeArchived }),
  });
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(null);
  // KI-08：搜索结果点击后，进入 Source 详情时定位/高亮对应 Evidence。
  // 保留 evidenceId + 命中片段用于详情面板滚动与高亮；定位完成后清空。
  const [highlightEvidenceId, setHighlightEvidenceId] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [bundleOpen, setBundleOpen] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSearch, setActiveSearch] = useState('');

  const uploadMutation = useMutation({
    mutationFn: ({ file, titleHint }: { file: File; titleHint: string }) =>
      uploadKnowledgeSource(file, titleHint),
    onSuccess: (data) => {
      if (data.deduplicated) {
        message.success('资料已导入，已进入已有 Source');
      } else {
        message.success('资料已导入');
      }
      queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY });
      setSelectedSourceId(data.source.id);
      setUploadOpen(false);
    },
    onError: (error: unknown) => {
      const detail = extractErrorMessage(error);
      message.error(`上传失败：${detail}`);
    },
  });

  const bundleMutation = useMutation({
    mutationFn: ({
      main,
      assets,
      titleHint,
    }: {
      main: File;
      assets: File[];
      titleHint: string;
    }) => uploadKnowledgeBundle(main, assets, titleHint),
    onSuccess: (data) => {
      if (data.deduplicated) {
        message.success('资料已导入，已进入已有 Source');
      } else {
        message.success('Bundle 已导入，图片以附件形式保留');
      }
      queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY });
      setSelectedSourceId(data.source.id);
      setBundleOpen(false);
    },
    onError: (error: unknown) => {
      const detail = extractErrorMessage(error);
      message.error(`Bundle 上传失败：${detail}`);
    },
  });

  const pasteMutation = useMutation({
    mutationFn: ({
      paste,
      titleHint,
      originUrl,
    }: {
      paste: string;
      titleHint: string;
      originUrl: string;
    }) => pasteKnowledgeSource(paste, { titleHint, originUrl }),
    onSuccess: (data) => {
      if (data.deduplicated) {
        message.success('资料已导入，已进入已有 Source');
      } else {
        message.success('正文已导入');
      }
      queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY });
      setSelectedSourceId(data.source.id);
      setPasteOpen(false);
    },
    onError: (error: unknown) => {
      const detail = extractErrorMessage(error);
      message.error(`粘贴失败：${detail}`);
    },
  });

  const searchMutation = useMutation({
    mutationFn: (query: string) => searchKnowledgeEvidence(query, { limit: 20 }),
    onSuccess: (data) => {
      setActiveSearch(data.query);
    },
  });

  const handleSearch = () => {
    if (!searchQuery.trim()) {
      message.warning('请输入搜索关键词');
      return;
    }
    searchMutation.mutate(searchQuery);
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={3} style={{ margin: 0 }}>
        资料来源
      </Title>
      <Paragraph type="secondary" style={{ margin: '6px 0 16px' }}>
        上传 Markdown/Text、上传图文 Bundle，或直接粘贴正文；系统按自然结构生成 Evidence，并提供关键词检索。
      </Paragraph>

      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Space wrap>
          <Button type="primary" icon={<InboxOutlined />} onClick={() => setUploadOpen(true)}>
            上传 Markdown / Text
          </Button>
          <Button icon={<PictureOutlined />} onClick={() => setBundleOpen(true)}>
            上传图文 Bundle
          </Button>
          <Button icon={<FormOutlined />} onClick={() => setPasteOpen(true)}>
            粘贴正文
          </Button>
          <Input
            placeholder="搜索 Evidence（中文/英文关键词）"
            style={{ width: 320 }}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            onPressEnter={handleSearch}
            prefix={<SearchOutlined />}
          />
          <Button onClick={handleSearch} loading={searchMutation.isPending}>
            搜索
          </Button>
          <Space size={6} align="center">
            <Switch
              checked={includeArchived}
              onChange={(checked) => setIncludeArchived(checked)}
              aria-label="显示归档资料"
            />
            <Text type="secondary">显示归档资料</Text>
          </Space>
        </Space>

        {searchMutation.data ? (
          <SearchResultsPanel
            query={activeSearch}
            hits={searchMutation.data.hits}
            onPick={(sourceId, evidenceId) => {
              setSelectedSourceId(sourceId);
              setHighlightEvidenceId(evidenceId);
            }}
          />
        ) : null}

        <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 16 }}>
          <SourceListPanel
            sources={sourcesQuery.data ?? []}
            loading={sourcesQuery.isLoading}
            selectedId={selectedSourceId}
            onSelect={(id) => {
              setSelectedSourceId(id);
              setHighlightEvidenceId(null);
            }}
          />
          <SourceDetailPanel
            sourceId={selectedSourceId}
            highlightEvidenceId={highlightEvidenceId}
            onHighlightConsumed={() => setHighlightEvidenceId(null)}
          />
        </div>
      </Space>

      <UploadModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        uploading={uploadMutation.isPending}
        onSubmit={(file, titleHint) => uploadMutation.mutate({ file, titleHint })}
      />
      <BundleModal
        open={bundleOpen}
        onClose={() => setBundleOpen(false)}
        uploading={bundleMutation.isPending}
        onSubmit={(main, assets, titleHint) =>
          bundleMutation.mutate({ main, assets, titleHint })
        }
      />
      <PasteModal
        open={pasteOpen}
        onClose={() => setPasteOpen(false)}
        submitting={pasteMutation.isPending}
        onSubmit={(paste, titleHint, originUrl) =>
          pasteMutation.mutate({ paste, titleHint, originUrl })
        }
      />
      <DedupHintBanner />
    </div>
  );
}

function SourceListPanel({
  sources,
  loading,
  selectedId,
  onSelect,
}: {
  sources: KnowledgeSource[];
  loading: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  if (loading) {
    return (
      <div style={{ padding: 24 }}>
        <Spin />
      </div>
    );
  }
  if (!sources.length) {
    return (
      <div style={{ border: '1px solid var(--op-border, #eee)', padding: 24, borderRadius: 8 }}>
        <Empty description="还没有资料来源" />
      </div>
    );
  }
  return (
    <div style={{ border: '1px solid var(--op-border, #eee)', borderRadius: 8, padding: 8 }}>
      <List
        dataSource={sources}
        rowKey={(item) => item.id}
        renderItem={(item) => (
          <List.Item
            key={item.id}
            onClick={() => onSelect(item.id)}
            style={{
              cursor: 'pointer',
              padding: '8px 12px',
              background:
                selectedId === item.id ? 'var(--op-active-bg, #e6f4ff)' : 'transparent',
              borderRadius: 4,
            }}
          >
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Text strong>{item.title}</Text>
              <Space size={6} wrap>
                <Badge color="blue" text={STATUS_LABEL[item.lifecycle] ?? item.lifecycle} />
                <Badge
                  color="gold"
                  text={EXTRACTION_LABEL[item.extraction_status] ?? item.extraction_status}
                />
                <Badge
                  color="purple"
                  text={BRIEF_LABEL[item.brief_status] ?? item.brief_status}
                />
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {item.main_filename} · {formatBytes(item.total_bytes)}
              </Text>
            </Space>
          </List.Item>
        )}
      />
    </div>
  );
}

function SourceDetailPanel({
  sourceId,
  highlightEvidenceId,
  onHighlightConsumed,
}: {
  sourceId: number | null;
  highlightEvidenceId: string | null;
  onHighlightConsumed: () => void;
}) {
  if (sourceId == null) {
    return (
      <div style={{ border: '1px solid var(--op-border, #eee)', padding: 24, borderRadius: 8 }}>
        <Empty description="选择左侧的 Source 查看详情" />
      </div>
    );
  }
  return (
    <SourceDetailContent
      sourceId={sourceId}
      highlightEvidenceId={highlightEvidenceId}
      onHighlightConsumed={onHighlightConsumed}
    />
  );
}

function SourceDetailContent({
  sourceId,
  highlightEvidenceId,
  onHighlightConsumed,
}: {
  sourceId: number;
  highlightEvidenceId: string | null;
  onHighlightConsumed: () => void;
}) {
  const queryClient = useQueryClient();
  const sourceQuery = useQuery({
    queryKey: ['knowledge', 'source', sourceId],
    queryFn: () => fetchKnowledgeSource(sourceId),
  });
  const evidenceQuery = useQuery({
    queryKey: ['knowledge', 'source', sourceId, 'evidence'],
    queryFn: () => fetchKnowledgeSourceEvidence(sourceId, { limit: 50 }),
  });
  const briefQuery = useQuery({
    queryKey: ['knowledge', 'source', sourceId, 'brief'],
    queryFn: () => fetchKnowledgeSourceBrief(sourceId),
    refetchInterval: false,
  });
  const jobsQuery = useQuery({
    queryKey: ['knowledge', 'source', sourceId, 'jobs'],
    queryFn: () => fetchKnowledgeSourceJobs(sourceId),
  });
  const briefRebuildMutation = useMutation({
    mutationFn: (id: number) => rebuildKnowledgeSourceBrief(id),
    onSuccess: () => {
      message.success('已请求重新生成 Brief');
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'source', sourceId] });
      queryClient.invalidateQueries({
        queryKey: ['knowledge', 'source', sourceId, 'brief'],
      });
    },
    onError: (error: unknown) => {
      const detail = extractErrorMessage(error);
      message.error(`Brief 重建失败：${detail}`);
    },
  });
  const [briefCitationTarget, setBriefCitationTarget] = useState<string | null>(
    null,
  );
  const handleCitationJump = (evidenceId: string) => {
    setBriefCitationTarget(evidenceId);
  };
  const [titleEditorOpen, setTitleEditorOpen] = useState(false);
  const [editingTitle, setEditingTitle] = useState('');
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteConfirmationText, setDeleteConfirmationText] = useState('');
  const titleMutation = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      updateKnowledgeSourceTitle(id, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'source', sourceId] });
      message.success('展示标题已更新');
      setTitleEditorOpen(false);
    },
    onError: (error: unknown) => {
      const detail = extractErrorMessage(error);
      message.error(`标题更新失败：${detail}`);
    },
  });
  const archiveMutation = useMutation({
    mutationFn: (id: number) => archiveKnowledgeSource(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'source', sourceId] });
      message.success('资料已归档');
    },
    onError: (error: unknown) => {
      const detail = extractErrorMessage(error);
      message.error(`归档失败：${detail}`);
    },
  });
  const unarchiveMutation = useMutation({
    mutationFn: (id: number) => unarchiveKnowledgeSource(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ['knowledge', 'source', sourceId] });
      message.success('资料已取消归档');
    },
    onError: (error: unknown) => {
      const detail = extractErrorMessage(error);
      message.error(`取消归档失败：${detail}`);
    },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteKnowledgeSource(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY });
      message.success('资料已永久删除');
      setDeleteConfirmOpen(false);
      setDeleteConfirmationText('');
    },
    onError: (error: unknown) => {
      const detail = extractErrorMessage(error);
      message.error(`删除失败：${detail}`);
    },
  });
  if (sourceQuery.isLoading || !sourceQuery.data) {
    return (
      <div style={{ padding: 24 }}>
        <Spin />
      </div>
    );
  }
  const source = sourceQuery.data;
  const openTitleEditor = () => {
    setEditingTitle(source.display_title || source.title_hint || '');
    setTitleEditorOpen(true);
  };
  const isArchived = source.lifecycle === 'archived';
  return (
    <div style={{ border: '1px solid var(--op-border, #eee)', padding: 16, borderRadius: 8 }}>
      <Space align="start" style={{ justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ marginTop: 0, marginBottom: 0 }}>
          {source.title}
        </Title>
        <Space size={6} wrap>
          <Button size="small" icon={<EditOutlined />} onClick={openTitleEditor}>
            编辑标题
          </Button>
          {isArchived ? (
            <Button
              size="small"
              onClick={() => unarchiveMutation.mutate(sourceId)}
              loading={unarchiveMutation.isPending}
            >
              取消归档
            </Button>
          ) : (
            <Button
              size="small"
              onClick={() => archiveMutation.mutate(sourceId)}
              loading={archiveMutation.isPending}
            >
              归档
            </Button>
          )}
        </Space>
      </Space>
      <Space direction="vertical" size={4} style={{ marginBottom: 12, marginTop: 8 }}>
        <Text type="secondary">文件名：{source.main_filename}</Text>
        <Text type="secondary">大小：{formatBytes(source.total_bytes)}</Text>
        <Text type="secondary">展示标题：{source.display_title || '—（使用推导标题）'}</Text>
        <Text type="secondary">推导标题：{source.title_hint || '—'}</Text>
        <Text type="secondary">导入时间：{formatDateTime(source.created_at)}</Text>
        {source.archived_at ? (
          <Text type="secondary">归档时间：{formatDateTime(source.archived_at)}</Text>
        ) : null}
      </Space>

      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <StatusBlock source={source} />
        <BriefBlock
          sourceId={sourceId}
          briefStatus={source.brief_status}
          data={briefQuery.data}
          loading={briefQuery.isLoading}
          onRebuild={() => briefRebuildMutation.mutate(sourceId)}
          rebuilding={briefRebuildMutation.isPending}
          onCitationJump={handleCitationJump}
        />
        <EvidenceBlock
          evidence={evidenceQuery.data?.items ?? []}
          loading={evidenceQuery.isLoading}
          sourceId={sourceId}
          highlightEvidenceId={highlightEvidenceId ?? briefCitationTarget}
          onHighlightConsumed={() => {
            onHighlightConsumed();
            setBriefCitationTarget(null);
          }}
        />
        <JobsBlock
          data={jobsQuery.data ?? { jobs: [], origins: [] }}
          loading={jobsQuery.isLoading}
        />
      </Space>

      <div
        style={{
          marginTop: 16,
          padding: 12,
          border: '1px solid var(--op-danger-border, #ffccc7)',
          background: 'var(--op-danger-bg, #fff2f0)',
          borderRadius: 8,
        }}
      >
        <Title level={5} style={{ color: '#cf1322', marginTop: 0 }}>
          危险操作
        </Title>
        <Paragraph type="secondary" style={{ marginBottom: 8 }}>
          永久删除会清除原件、附件、Evidence、Snapshot、Brief 与 Job 历史,不可恢复。
          删除后相同内容可作为新 Source 重新导入。
        </Paragraph>
        <Button
          danger
          icon={<DeleteOutlined />}
          onClick={() => {
            setDeleteConfirmationText('');
            setDeleteConfirmOpen(true);
          }}
        >
          永久删除该资料
        </Button>
      </div>

      <Modal
        title="编辑展示标题"
        open={titleEditorOpen}
        onCancel={() => setTitleEditorOpen(false)}
        onOk={() =>
          titleMutation.mutate({ id: sourceId, title: editingTitle.trim() })
        }
        okButtonProps={{ loading: titleMutation.isPending }}
        okText="保存"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <Input
            placeholder="留空则回退到推导标题"
            value={editingTitle}
            onChange={(event) => setEditingTitle(event.target.value)}
            maxLength={85}
            showCount
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            修改展示标题不会触发重新解析或重新生成 Brief,Evidence ID 保持不变。
          </Text>
        </Space>
      </Modal>

      <Modal
        title="永久删除该资料"
        open={deleteConfirmOpen}
        onCancel={() => {
          setDeleteConfirmOpen(false);
          setDeleteConfirmationText('');
        }}
        okText="我已确认,永久删除"
        cancelText="取消"
        okButtonProps={{
          danger: true,
          loading: deleteMutation.isPending,
          disabled: deleteConfirmationText.trim() !== '删除',
        }}
        onOk={() => deleteMutation.mutate(sourceId)}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <Alert
            type="error"
            showIcon
            message="此操作不可恢复"
            description="删除后原件、Evidence、附件和 Job 历史都会被清除。如果之后再次上传相同内容,会得到全新的 Source。"
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            为防止误操作,请在下方输入框中输入"删除"以确认。
          </Text>
          <Input
            placeholder='输入"删除"以确认'
            value={deleteConfirmationText}
            onChange={(event) => setDeleteConfirmationText(event.target.value)}
          />
        </Space>
      </Modal>
    </div>
  );
}

function StatusBlock({ source }: { source: KnowledgeSource }) {
  const extractionError =
    source.extraction_status === 'failed' && source.extraction_error_message
      ? source.extraction_error_message
      : '';
  const briefError =
    source.brief_status === 'failed' && source.brief_error_message
      ? source.brief_error_message
      : '';
  return (
    <div>
      <Tabs
        defaultActiveKey="status"
        items={[
          {
            key: 'status',
            label: '处理记录',
            children: (
              <Space direction="vertical" style={{ width: '100%' }}>
                <StatusLine label="生命周期" value={STATUS_LABEL[source.lifecycle] ?? source.lifecycle} />
                <StatusLine
                  label="Extraction"
                  value={EXTRACTION_LABEL[source.extraction_status] ?? source.extraction_status}
                />
                <StatusLine
                  label="Brief"
                  value={BRIEF_LABEL[source.brief_status] ?? source.brief_status}
                />
                <StatusLine
                  label="Brief 暂缓原因"
                  value={source.brief_block_reason || '—'}
                />
                {extractionError ? (
                  <Alert type="error" showIcon message="Extraction 失败" description={extractionError} />
                ) : null}
                {briefError ? (
                  <Alert type="error" showIcon message="Brief 失败" description={briefError} />
                ) : null}
              </Space>
            ),
          },
          {
            key: 'original',
            label: '原始 Markdown',
            children: (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Button href={buildKnowledgeSourceContentUrl(source.id)} target="_blank">
                  下载原件
                </Button>
                <Text type="secondary">
                  原始 Markdown 按字节流下载，不经过模型改写。
                </Text>
              </Space>
            ),
          },
        ]}
      />
    </div>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <Space size={12}>
      <Text type="secondary" style={{ width: 96 }}>
        {label}
      </Text>
      <Text>{value}</Text>
    </Space>
  );
}

function BriefBlock({
  sourceId,
  briefStatus,
  data,
  loading,
  onRebuild,
  rebuilding,
  onCitationJump,
}: {
  sourceId: number;
  briefStatus: string;
  data: KnowledgeSourceBriefResponse | undefined;
  loading: boolean;
  onRebuild: () => void;
  rebuilding: boolean;
  onCitationJump: (evidenceId: string) => void;
}) {
  if (loading) {
    return <Spin />;
  }
  const brief: KnowledgeSourceBrief | null = data?.brief ?? null;
  const latestAttempt: KnowledgeBriefAttempt | null = data?.latest_attempt ?? null;
  const blockReason = data?.brief_block_reason ?? '';
  const errorMessage = data?.brief_error_message ?? '';
  const showEmpty = briefStatus === 'not_started' || (!brief && !latestAttempt);

  return (
    <div
      style={{
        border: '1px solid var(--op-border, #eee)',
        borderRadius: 8,
        padding: 12,
      }}
    >
      <Space
        align="start"
        style={{ justifyContent: 'space-between', width: '100%', marginBottom: 8 }}
      >
        <Title level={5} style={{ margin: 0 }}>
          Brief 导读
        </Title>
        <Space size={6} wrap>
          <Badge color="purple" text={BRIEF_LABEL[briefStatus] ?? briefStatus} />
          <Button
            size="small"
            onClick={onRebuild}
            loading={rebuilding}
            disabled={briefStatus === 'processing'}
          >
            {brief ? '重建 Brief' : '生成 Brief'}
          </Button>
        </Space>
      </Space>
      {blockReason ? (
        <Alert
          type="warning"
          showIcon
          message={`Brief 暂缓：${blockReason}`}
          description="请先在设置中配置满足 96K context 的 Provider，然后点击生成 Brief。"
        />
      ) : null}
      {errorMessage && briefStatus === 'failed' ? (
        <Alert
          type="error"
          showIcon
          message="最近一次 Brief 校验未通过"
          description={errorMessage}
          style={{ marginTop: 8 }}
        />
      ) : null}
      {showEmpty && !blockReason ? (
        <Empty description="尚未生成 Brief，可在上方点击「生成 Brief」" />
      ) : null}
      {brief ? (
        <BriefPayloadView brief={brief} onCitationJump={onCitationJump} />
      ) : null}
      {latestAttempt && latestAttempt.status !== 'succeeded' ? (
        <BriefAttemptInspector attempt={latestAttempt} />
      ) : null}
      <Text type="secondary" style={{ fontSize: 11 }}>
        Source ID：{sourceId}
      </Text>
    </div>
  );
}

function BriefPayloadView({
  brief,
  onCitationJump,
}: {
  brief: KnowledgeSourceBrief;
  onCitationJump: (evidenceId: string) => void;
}) {
  const { payload } = brief;
  return (
    <Space direction="vertical" size={10} style={{ width: '100%', marginTop: 8 }}>
      <BriefStatementList
        title="概述"
        items={payload.overview}
        onCitationJump={onCitationJump}
      />
      <BriefStatementList
        title="关键要点"
        items={payload.key_points}
        onCitationJump={onCitationJump}
      />
      <div>
        <Title level={5}>章节导读</Title>
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          {payload.section_guides.map((item, index) => (
            <div
              key={`${item.section_key}-${index}`}
              style={{
                border: '1px solid var(--op-border, #eee)',
                borderRadius: 4,
                padding: 8,
              }}
            >
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Space size={6} wrap>
                  <Badge color="blue" text={item.heading_path.join(' / ')} />
                </Space>
                <Text>{item.summary}</Text>
                <BriefCitationChips
                  evidenceIds={item.evidence_ids}
                  onJump={onCitationJump}
                />
              </Space>
            </div>
          ))}
        </Space>
      </div>
      <BriefStatementList
        title="局限与未覆盖"
        items={payload.limitations}
        onCitationJump={onCitationJump}
      />
      <div>
        <Title level={5}>章节覆盖</Title>
        <Space wrap>
          {payload.coverage.map((item) => (
            <Badge
              key={item.section_key}
              color={item.status === 'covered' ? 'green' : 'default'}
              text={`${item.section_key}${
                item.status === 'skipped' ? `（已跳过：${item.skipped_reason || '—'}）` : ''
              }`}
            />
          ))}
        </Space>
      </div>
    </Space>
  );
}

function BriefStatementList({
  title,
  items,
  onCitationJump,
}: {
  title: string;
  items: BriefStatement[];
  onCitationJump: (evidenceId: string) => void;
}) {
  if (!items.length) {
    return null;
  }
  return (
    <div>
      <Title level={5}>{title}</Title>
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        {items.map((item, index) => (
          <div
            key={`${title}-${index}`}
            style={{
              border: '1px solid var(--op-border, #eee)',
              borderRadius: 4,
              padding: 8,
            }}
          >
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text>{item.statement}</Text>
              <BriefCitationChips
                evidenceIds={item.evidence_ids}
                onJump={onCitationJump}
              />
            </Space>
          </div>
        ))}
      </Space>
    </div>
  );
}

function BriefCitationChips({
  evidenceIds,
  onJump,
}: {
  evidenceIds: string[];
  onJump: (evidenceId: string) => void;
}) {
  if (!evidenceIds.length) {
    return null;
  }
  return (
    <Space size={4} wrap>
      {evidenceIds.map((id) => (
        <Button
          key={id}
          size="small"
          type="link"
          style={{ padding: 0, height: 'auto', fontSize: 11 }}
          onClick={() => onJump(id)}
        >
          {id}
        </Button>
      ))}
    </Space>
  );
}

function BriefAttemptInspector({ attempt }: { attempt: KnowledgeBriefAttempt }) {
  return (
    <Alert
      type={attempt.status === 'failed' ? 'error' : 'info'}
      showIcon
      message={`最近 Attempt 状态：${attempt.status}${
        attempt.repair_count ? `（修复 ${attempt.repair_count} 次）` : ''
      }`}
      description={
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Provider: {attempt.provider_id} / {attempt.provider_model}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Context: {attempt.context_window} · Prompt: {attempt.prompt_version}
          </Text>
          {attempt.error_message ? (
            <Text type="danger" style={{ fontSize: 12 }}>
              {attempt.error_message}
            </Text>
          ) : null}
        </Space>
      }
    />
  );
}

function EvidenceBlock({
  evidence,
  loading,
  sourceId,
  highlightEvidenceId,
  onHighlightConsumed,
}: {
  evidence: KnowledgeEvidence[];
  loading: boolean;
  sourceId: number;
  highlightEvidenceId: string | null;
  onHighlightConsumed: () => void;
}) {
  const highlightRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!highlightEvidenceId) return;
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    onHighlightConsumed();
  }, [highlightEvidenceId, onHighlightConsumed]);
  if (loading) {
    return <Spin />;
  }
  if (!evidence.length) {
    return (
      <div>
        <Title level={5}>Evidence</Title>
        <Empty description="尚未生成 Evidence" />
      </div>
    );
  }
  return (
    <div>
      <Title level={5}>Evidence（共 {evidence.length} 条）</Title>
      <List
        dataSource={evidence}
        rowKey={(item) => item.id}
        renderItem={(item) => {
          const isHighlighted = highlightEvidenceId === item.id;
          return (
            <List.Item>
              <div
                ref={isHighlighted ? highlightRef : undefined}
                style={{
                  width: '100%',
                  padding: 8,
                  borderRadius: 4,
                  background: isHighlighted
                    ? 'var(--op-highlight-bg, #fffbe6)'
                    : 'transparent',
                  border: isHighlighted
                    ? '1px solid var(--op-highlight-border, #ffe58f)'
                    : '1px solid transparent',
                  transition: 'background 200ms ease',
                }}
              >
                <Space direction="vertical" size={2} style={{ width: '100%' }}>
                  <Space size={8}>
                    <Badge color="cyan" text={item.block_kind} />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      行 {item.line_start}-{item.line_end}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      字符 {item.char_start}-{item.char_end}
                    </Text>
                    {isHighlighted ? (
                      <Badge color="gold" text="搜索命中" />
                    ) : null}
                  </Space>
                  {item.heading_path.length ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      路径：{item.heading_path.join(' / ')}
                    </Text>
                  ) : null}
                  {item.kind === 'asset' && item.asset_id != null ? (
                    <AssetEvidenceView
                      sourceId={sourceId}
                      assetId={item.asset_id}
                      alt={item.search_text}
                    />
                  ) : null}
                  <Text>{item.canonical_excerpt}</Text>
                  <Text code style={{ fontSize: 11 }}>
                    {item.id}
                  </Text>
                </Space>
              </div>
            </List.Item>
          );
        }}
      />
    </div>
  );
}

function AssetEvidenceView({
  sourceId,
  assetId,
  alt,
}: {
  sourceId: number;
  assetId: number;
  alt: string;
}) {
  const url = buildKnowledgeAssetContentUrl(sourceId, assetId);
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      {/* eslint-disable-next-line jsx-a11y/alt-text */}
      <img
        src={url}
        alt={alt || 'Bundle 附件'}
        loading="lazy"
        style={{
          maxWidth: '100%',
          maxHeight: 320,
          border: '1px solid var(--op-border, #eee)',
          borderRadius: 4,
          objectFit: 'contain',
        }}
      />
      <Button size="small" href={url} target="_blank" rel="noopener noreferrer">
        下载原图
      </Button>
    </Space>
  );
}

function JobsBlock({
  data,
  loading,
}: {
  data: KnowledgeSourceJobsResponse;
  loading: boolean;
}) {
  const queryClient = useQueryClient();
  const cancelMutation = useMutation({
    mutationFn: (jobId: number) => cancelKnowledgeJob(jobId),
    onSuccess: () => {
      message.success('已请求取消');
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
    },
    onError: (error) => {
      const text = error instanceof Error ? error.message : '取消失败';
      message.error(text);
    },
  });
  if (loading) {
    return <Spin />;
  }
  return (
    <div>
      <Title level={5}>后台任务</Title>
      <List
        dataSource={data.jobs}
        rowKey={(item) => item.id}
        renderItem={(item) => (
          <List.Item>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Space size={8} wrap>
                <Badge color="gold" text={item.kind} />
                <Badge color="blue" text={JOB_STATUS_LABEL[item.status] ?? item.status} />
                <Text type="secondary">队列：{item.queue}</Text>
                {item.canceled ? (
                  <Badge color="red" text="已取消" />
                ) : null}
              </Space>
              {item.progress > 0 ? <Progress percent={item.progress} size="small" /> : null}
              <Text type="secondary" style={{ fontSize: 12 }}>
                阶段：{item.stage || '—'} · 创建于 {formatDateTime(item.created_at)}
              </Text>
              {(item.retry_count ?? 0) > 0 ? (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  重试次数：{item.retry_count}
                  {item.next_retry_at
                    ? ` · 下次重试 ${formatDateTime(item.next_retry_at)}`
                    : ''}
                </Text>
              ) : null}
              {item.lease_owner ? (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Worker：{item.lease_owner}
                  {item.heartbeat_at ? ` · 心跳 ${formatDateTime(item.heartbeat_at)}` : ''}
                </Text>
              ) : null}
              {item.error_message ? (
                <Alert
                  type="error"
                  showIcon
                  message={item.error_message}
                  description={item.error_code ? `错误码：${item.error_code}` : undefined}
                />
              ) : null}
              {isJobCancellable(item) ? (
                <Button
                  size="small"
                  danger
                  loading={cancelMutation.isPending}
                  onClick={() => cancelMutation.mutate(item.id)}
                >
                  取消任务
                </Button>
              ) : null}
            </Space>
          </List.Item>
        )}
      />
      <Title level={5} style={{ marginTop: 16 }}>
        导入记录
      </Title>
      <List
        dataSource={data.origins}
        rowKey={(item) => item.id}
        renderItem={(item) => (
          <List.Item>
            <Space direction="vertical" size={2}>
              <Text>
                {item.import_method}：{item.original_filename || '未提供文件名'}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {item.origin_url ? `URL：${item.origin_url} · ` : ''}
                {formatDateTime(item.imported_at)}
              </Text>
            </Space>
          </List.Item>
        )}
      />
    </div>
  );
}

const JOB_STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '运行中',
  succeeded: '已完成',
  failed: '已失败',
  canceled: '已取消',
};

function isJobCancellable(job: KnowledgeJob): boolean {
  return !job.canceled && job.status !== 'succeeded' && job.status !== 'failed' && job.status !== 'canceled';
}

function DedupHintBanner() {
  // KI-05：内容寻址去重的稳定展示。相同字节、不同文件名 / 不同 URL 都会进入同一 Source;
  // 上传成功后会自动跳转到已有 Source。此 banner 在 SSR 时也可被 contract 测试发现。
  return (
    <Alert
      type="info"
      showIcon
      message="相同内容自动复用已有 Source"
      description="重复上传相同字节时,系统会让上传结果进入已有 Source,不会创建重复 Evidence;每次导入都会追加一条 Origin 记录。"
    />
  );
}

function SearchResultsPanel({
  query,
  hits,
  onPick,
}: {
  query: string;
  hits: import('@/types/knowledge').KnowledgeEvidenceSearchHit[];
  onPick: (sourceId: number, evidenceId: string) => void;
}) {
  if (!hits.length) {
    return (
      <Alert
        type="info"
        showIcon
        message={`未匹配 Evidence：${query}`}
        description="尝试更宽的关键词，或确认 Extraction 已完成。"
      />
    );
  }
  return (
    <Alert
      type="success"
      showIcon
      message={`命中 ${hits.length} 条 Evidence：${query}`}
      description={
        <List
          dataSource={hits}
          rowKey={(item) => item.evidence_id}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="open"
                  size="small"
                  onClick={() => onPick(item.source_id, item.evidence_id)}
                >
                  打开并定位
                </Button>,
              ]}
            >
              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                <Space size={6}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    Source #{item.source_id}
                  </Text>
                  <Badge color="cyan" text={item.block_kind} />
                  {item.heading_path.length ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {item.heading_path.join(' / ')}
                    </Text>
                  ) : null}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    行 {item.line_start}-{item.line_end}
                  </Text>
                </Space>
                <Text>{item.snippet}</Text>
                <Text code style={{ fontSize: 11 }}>
                  {item.evidence_id}
                </Text>
              </Space>
            </List.Item>
          )}
        />
      }
    />
  );
}

function UploadModal({
  open,
  onClose,
  uploading,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  uploading: boolean;
  onSubmit: (file: File, titleHint: string) => void;
}) {
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [titleHint, setTitleHint] = useState('');
  const pickedFile = fileList[0]?.originFileObj as File | undefined;

  const handleUpload = () => {
    if (!pickedFile) {
      message.warning('请选择一个 Markdown 或 Text 文件');
      return;
    }
    onSubmit(pickedFile, titleHint);
  };

  return (
    <Modal
      title="上传 Markdown / Text 资料"
      open={open}
      onCancel={() => {
        setFileList([]);
        setTitleHint('');
        onClose();
      }}
      onOk={handleUpload}
      okButtonProps={{ loading: uploading }}
      okText="开始导入"
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Upload.Dragger
          accept=".md,.markdown,.mdx,.txt,text/markdown,text/plain"
          maxCount={1}
          beforeUpload={() => false}
          fileList={fileList}
          onChange={({ fileList: next }) => setFileList(next)}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽 .md / .txt 文件到此处</p>
          <p className="ant-upload-hint">
            单文件最大 5 MiB / 64,000 tokens；UTF-8（含 BOM）、UTF-16 BOM 或高置信 GBK/GB18030
          </p>
        </Upload.Dragger>
        <Input
          placeholder="可选：展示标题（不填则用文件名或首个 # 标题）"
          value={titleHint}
          onChange={(event) => setTitleHint(event.target.value)}
        />
      </Space>
    </Modal>
  );
}

function BundleModal({
  open,
  onClose,
  uploading,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  uploading: boolean;
  onSubmit: (main: File, assets: File[], titleHint: string) => void;
}) {
  const [mainFileList, setMainFileList] = useState<UploadFile[]>([]);
  const [assetFileList, setAssetFileList] = useState<UploadFile[]>([]);
  const [titleHint, setTitleHint] = useState('');

  const mainFile = mainFileList[0]?.originFileObj as File | undefined;
  const assetFiles = assetFileList
    .map((item) => item.originFileObj as File | undefined)
    .filter((value): value is File => Boolean(value));

  const handleSubmit = () => {
    if (!mainFile) {
      message.warning('请选择 Markdown 主文件');
      return;
    }
    if (assetFiles.length === 0) {
      message.warning('Bundle 至少需要一张图片附件');
      return;
    }
    onSubmit(mainFile, assetFiles, titleHint);
  };

  return (
    <Modal
      title="上传图文 Bundle"
      open={open}
      onCancel={() => {
        setMainFileList([]);
        setAssetFileList([]);
        setTitleHint('');
        onClose();
      }}
      onOk={handleSubmit}
      okButtonProps={{ loading: uploading }}
      okText="开始导入"
      width={640}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div>
          <Title level={5} style={{ marginBottom: 4 }}>
            Markdown 主文件
          </Title>
          <Upload.Dragger
            accept=".md,.markdown,.mdx,text/markdown"
            maxCount={1}
            beforeUpload={() => false}
            fileList={mainFileList}
            onChange={({ fileList: next }) => setMainFileList(next)}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽 .md 主文件</p>
            <p className="ant-upload-hint">主文件最大 5 MiB；图片引用必须使用扁平相对路径</p>
          </Upload.Dragger>
        </div>
        <div>
          <Title level={5} style={{ marginBottom: 4 }}>
            图片附件（PNG / JPEG / WebP）
          </Title>
          <Upload.Dragger
            accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
            multiple
            beforeUpload={() => false}
            fileList={assetFileList}
            onChange={({ fileList: next }) => setAssetFileList(next)}
          >
            <p className="ant-upload-drag-icon">
              <PictureOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽多张图片到此处</p>
            <p className="ant-upload-hint">
              单图 ≤ 10 MiB / 40 MP；Bundle 总大小 ≤ 50 MiB；附件数量 ≤ 50
            </p>
          </Upload.Dragger>
        </div>
        <Input
          placeholder="可选：展示标题（不填则用文件名或首个 # 标题）"
          value={titleHint}
          onChange={(event) => setTitleHint(event.target.value)}
        />
        <Alert
          type="info"
          showIcon
          message="系统不会 OCR 图片内容，也不会调用多模态模型"
          description="alt 文本作为作者原文参与检索；图片字节不会进入 FTS。"
        />
      </Space>
    </Modal>
  );
}

function PasteModal({
  open,
  onClose,
  submitting,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  submitting: boolean;
  onSubmit: (paste: string, titleHint: string, originUrl: string) => void;
}) {
  const [paste, setPaste] = useState('');
  const [titleHint, setTitleHint] = useState('');
  const [originUrl, setOriginUrl] = useState('');

  const handleSubmit = () => {
    if (!paste.trim()) {
      message.warning('请粘贴正文内容');
      return;
    }
    onSubmit(paste, titleHint, originUrl);
  };

  return (
    <Modal
      title="粘贴正文"
      open={open}
      onCancel={() => {
        setPaste('');
        setTitleHint('');
        setOriginUrl('');
        onClose();
      }}
      onOk={handleSubmit}
      okButtonProps={{ loading: submitting }}
      okText="开始导入"
      width={640}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Input.TextArea
          placeholder="在此粘贴 Markdown 正文（系统会作为虚拟 main.md 进入同一 Pipeline）"
          value={paste}
          onChange={(event) => setPaste(event.target.value)}
          autoSize={{ minRows: 8, maxRows: 18 }}
        />
        <Input
          placeholder="可选：展示标题（不填则用首个 # 标题或首段内容）"
          value={titleHint}
          onChange={(event) => setTitleHint(event.target.value)}
        />
        <Input
          placeholder="可选：来源 URL（仅作为 provenance 保存，系统不会发起网络请求）"
          value={originUrl}
          onChange={(event) => setOriginUrl(event.target.value)}
        />
      </Space>
    </Modal>
  );
}

function formatBytes(total: number): string {
  if (total < 1024) return `${total} B`;
  if (total < 1024 * 1024) return `${(total / 1024).toFixed(1)} KB`;
  return `${(total / 1024 / 1024).toFixed(2)} MB`;
}

function formatDateTime(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function extractErrorMessage(error: unknown): string {
  if (!error) return '未知错误';
  if (typeof error === 'object' && error !== null) {
    const maybeResponse = error as { response?: { data?: { error?: unknown } } };
    if (maybeResponse.response?.data?.error) {
      return String(maybeResponse.response.data.error);
    }
  }
  return String(error);
}
