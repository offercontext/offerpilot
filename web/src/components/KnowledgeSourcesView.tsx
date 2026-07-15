import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Alert,
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
  Tag,
  Tooltip,
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
  QuestionCircleOutlined,
  ReadOutlined,
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
  fetchKnowledgeSourceContent,
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
  BriefValidationReport,
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

// Status Pill 变体：替换 antd 彩色圆点 Badge，统一精致化状态标识
type PillVariant = 'indigo' | 'green' | 'amber' | 'rose' | 'gray' | 'violet' | 'cyan';

function Pill({ variant, children }: { variant: PillVariant; children: ReactNode }) {
  return (
    <span className={`op-pill op-pill--${variant}`}>
      <span className="op-pill-dot" />
      {children}
    </span>
  );
}

function lifecycleVariant(status: string): PillVariant {
  switch (status) {
    case 'active':
      return 'green';
    case 'archived':
      return 'gray';
    case 'deleting':
      return 'rose';
    default:
      return 'gray';
  }
}

function extractionVariant(status: string): PillVariant {
  switch (status) {
    case 'extracted':
      return 'indigo';
    case 'processing':
      return 'amber';
    case 'failed':
      return 'rose';
    default:
      return 'gray';
  }
}

function briefVariant(status: string): PillVariant {
  switch (status) {
    case 'ready':
      return 'violet';
    case 'processing':
    case 'pending':
    case 'outdated':
      return 'amber';
    case 'failed':
      return 'rose';
    default:
      return 'gray';
  }
}

function jobStatusVariant(status: string): PillVariant {
  switch (status) {
    case 'succeeded':
      return 'green';
    case 'running':
      return 'indigo';
    case 'pending':
      return 'amber';
    case 'failed':
      return 'rose';
    default:
      return 'gray';
  }
}

export default function KnowledgeSourcesView() {
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
      <div className="knowledge-page-header">
        <div className="knowledge-page-header-row">
          <span className="knowledge-page-mark" />
          <Title level={3} className="knowledge-page-title">
            资料来源
          </Title>
          <span className="knowledge-page-count">
            共 <b>{sourcesQuery.data?.length ?? 0}</b> 个来源
          </span>
        </div>
        <Paragraph type="secondary" className="knowledge-page-subtitle">
          上传 Markdown/Text、上传图文 Bundle，或直接粘贴正文；系统按自然结构生成 Evidence，并提供关键词检索。
        </Paragraph>
      </div>

      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div className="knowledge-sources-toolbar">
          <Button
            type="primary"
            className="op-ai-btn"
            icon={<InboxOutlined />}
            onClick={() => setUploadOpen(true)}
          >
            上传 Markdown / Text
          </Button>
          <Button icon={<PictureOutlined />} onClick={() => setBundleOpen(true)}>
            上传图文 Bundle
          </Button>
          <Button icon={<FormOutlined />} onClick={() => setPasteOpen(true)}>
            粘贴正文
          </Button>
          <span className="knowledge-toolbar-spacer" />
          <Input
            placeholder="搜索 Evidence（中文/英文关键词）"
            className="knowledge-sources-search-input"
            style={{ width: 'min(320px, 100%)' }}
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
        </div>

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

        <div
          className="knowledge-sources-layout"
          style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 320px) minmax(0, 1fr)', gap: 16 }}
        >
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
            onDeleted={() => setSelectedSourceId(null)}
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
    <div className="knowledge-source-list">
      <div className="knowledge-source-list-head">
        <span>资料列表</span>
        <span>{sources.length}</span>
      </div>
      <List
        dataSource={sources}
        rowKey={(item) => item.id}
        split={false}
        renderItem={(item) => (
          <List.Item key={item.id}>
            <div
              className={`knowledge-source-item${selectedId === item.id ? ' is-selected' : ''}`}
              onClick={() => onSelect(item.id)}
            >
              <div className="knowledge-source-item-body">
                <Text className="knowledge-source-item-title">{item.title}</Text>
                <div className="knowledge-pill-row">
                  <Pill variant={lifecycleVariant(item.lifecycle)}>
                    {STATUS_LABEL[item.lifecycle] ?? item.lifecycle}
                  </Pill>
                  <Pill variant={extractionVariant(item.extraction_status)}>
                    {EXTRACTION_LABEL[item.extraction_status] ?? item.extraction_status}
                  </Pill>
                  <Pill variant={briefVariant(item.brief_status)}>
                    {BRIEF_LABEL[item.brief_status] ?? item.brief_status}
                  </Pill>
                </div>
                <Text className="knowledge-source-item-meta">
                  {item.main_filename} · {formatBytes(item.total_bytes)}
                </Text>
              </div>
            </div>
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
  onDeleted,
}: {
  sourceId: number | null;
  highlightEvidenceId: string | null;
  onHighlightConsumed: () => void;
  onDeleted: () => void;
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
      onDeleted={onDeleted}
    />
  );
}

function SourceDetailContent({
  sourceId,
  highlightEvidenceId,
  onHighlightConsumed,
  onDeleted,
}: {
  sourceId: number;
  highlightEvidenceId: string | null;
  onHighlightConsumed: () => void;
  onDeleted: () => void;
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
  const contentQuery = useQuery({
    queryKey: ['knowledge', 'source', sourceId, 'content'],
    queryFn: () => fetchKnowledgeSourceContent(sourceId),
  });
  const briefQuery = useQuery({
    queryKey: ['knowledge', 'source', sourceId, 'brief'],
    queryFn: () => fetchKnowledgeSourceBrief(sourceId),
    refetchInterval: (query) => {
      const status = query.state.data?.brief_status;
      return status === 'pending' || status === 'processing' ? 2000 : false;
    },
  });
  const jobsQuery = useQuery({
    queryKey: ['knowledge', 'source', sourceId, 'jobs'],
    queryFn: () => fetchKnowledgeSourceJobs(sourceId),
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs ?? [];
      return jobs.some((job) => job.status === 'pending' || job.status === 'running')
        ? 2000
        : false;
    },
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
  const [activeDetailTab, setActiveDetailTab] = useState('status');
  const handleCitationJump = (evidenceId: string) => {
    setBriefCitationTarget(evidenceId);
    setActiveDetailTab('evidence');
  };
  useEffect(() => {
    if (highlightEvidenceId) {
      setActiveDetailTab('evidence');
    }
  }, [highlightEvidenceId]);
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
      message.success('已提交永久删除，后台任务完成后资料将被移除');
      setDeleteConfirmOpen(false);
      setDeleteConfirmationText('');
      onDeleted();
    },
    onError: (error: unknown) => {
      const detail = extractErrorMessage(error);
      message.error(`删除失败：${detail}`);
    },
  });
  if (sourceQuery.isLoading) {
    return (
      <div style={{ padding: 24 }}>
        <Spin />
      </div>
    );
  }
  if (sourceQuery.isError || !sourceQuery.data) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="warning"
          showIcon
          message="资料详情不可用"
          description="该资料可能已删除或暂时无法读取，请从左侧选择其他资料。"
        />
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
    <div className="knowledge-source-detail">
      <div className="knowledge-source-detail-header">
        <div>
          <Title level={4} className="knowledge-source-detail-title">
            {source.title}
          </Title>
          <div className="knowledge-source-detail-statuses">
            <Pill variant={lifecycleVariant(source.lifecycle)}>
              {STATUS_LABEL[source.lifecycle] ?? source.lifecycle}
            </Pill>
            <Pill variant={extractionVariant(source.extraction_status)}>
              {EXTRACTION_LABEL[source.extraction_status] ?? source.extraction_status}
            </Pill>
            <Pill variant={briefVariant(source.brief_status)}>
              {BRIEF_LABEL[source.brief_status] ?? source.brief_status}
            </Pill>
          </div>
        </div>
        <Space size={6} wrap className="knowledge-source-actions">
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
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => {
              setDeleteConfirmationText('');
              setDeleteConfirmOpen(true);
            }}
          >
            永久删除该资料
          </Button>
        </Space>
      </div>

      <div className="knowledge-source-metadata">
        <SourceMetadataItem label="文件名" value={source.main_filename} />
        <SourceMetadataItem label="大小" value={formatBytes(source.total_bytes)} />
        <SourceMetadataItem label="展示标题" value={source.display_title || '使用推导标题'} />
        <SourceMetadataItem label="推导标题" value={source.title_hint || '无'} />
        {source.author ? <SourceMetadataItem label="作者" value={source.author} /> : null}
        {source.published_at ? (
          <SourceMetadataItem label="发布时间" value={formatDateTime(source.published_at)} />
        ) : null}
        {source.provenance?.url ? (
          <SourceMetadataItem label="来源 URL" value={source.provenance.url} />
        ) : null}
        <SourceMetadataItem label="导入时间" value={formatDateTime(source.created_at)} />
        <SourceMetadataItem
          label="Evidence"
          value={evidenceQuery.isLoading ? '—' : `${evidenceQuery.data?.items.length ?? 0} 条`}
        />
      </div>

      <BriefBlock
        sourceId={sourceId}
        briefStatus={source.brief_status}
        data={briefQuery.data}
        loading={briefQuery.isLoading}
        onRebuild={() => briefRebuildMutation.mutate(sourceId)}
        rebuilding={briefRebuildMutation.isPending}
        onCitationJump={handleCitationJump}
      />

      <Tabs
        className="knowledge-source-tabs"
        activeKey={activeDetailTab}
        onChange={setActiveDetailTab}
        items={[
          {
            key: 'status',
            label: '处理记录',
            children: <StatusBlock source={source} origins={jobsQuery.data?.origins ?? []} />,
          },
          {
            key: 'evidence',
            label: `Evidence${evidenceQuery.data?.items.length ? ` (${evidenceQuery.data.items.length})` : ''}`,
            children: (
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
            ),
          },
          {
            key: 'original',
            label: '原始 Markdown',
            children: (
              <OriginalMarkdownBlock
                sourceId={sourceId}
                content={contentQuery.data}
                loading={contentQuery.isLoading}
                error={contentQuery.isError}
              />
            ),
          },
          {
            key: 'jobs',
            label: '后台任务',
            children: (
              <JobsBlock
                data={jobsQuery.data ?? { jobs: [], origins: [] }}
                loading={jobsQuery.isLoading}
              />
            ),
          },
        ]}
      />

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
          <div className="knowledge-delete-warning">
            <Title level={5}>危险操作</Title>
            <Paragraph type="secondary">
              永久删除会清除原件、附件、Evidence、Snapshot、Brief 与 Job 历史,不可恢复。
              删除后相同内容可作为新 Source 重新导入。
            </Paragraph>
          </div>
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

function SourceMetadataItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="knowledge-source-metadata-item">
      <span className="knowledge-meta-label">{label}</span>
      <span className="knowledge-meta-value">{value}</span>
    </div>
  );
}

function StatusBlock({
  source,
  origins,
}: {
  source: KnowledgeSource;
  origins: KnowledgeSourceJobsResponse['origins'];
}) {
  const extractionError =
    source.extraction_status === 'failed' && source.extraction_error_message
      ? source.extraction_error_message
      : '';
  const filterSummary = source.evidence_policy_summary;
  const filteredTotal = filterSummary?.filtered_block_total ?? 0;
  return (
    <div className="knowledge-status-record">
      <StatusLine label="生命周期" value={STATUS_LABEL[source.lifecycle] ?? source.lifecycle} />
      <StatusLine
        label="Extraction"
        value={EXTRACTION_LABEL[source.extraction_status] ?? source.extraction_status}
      />
      <StatusLine label="Brief" value={BRIEF_LABEL[source.brief_status] ?? source.brief_status} />
      <StatusLine label="Brief 暂缓原因" value={source.brief_block_reason || '无'} />
      {extractionError ? (
        <Alert type="error" showIcon message="Extraction 失败" description={extractionError} />
      ) : null}
      {filterSummary && filteredTotal > 0 ? (
        <div className="knowledge-status-filter-summary">
          <Space size={4} align="center">
            <Title level={5}>Evidence 过滤统计</Title>
            <Tooltip title="系统在生成 Evidence 时按确定性规则过滤作者卡、阅读数、导航、图片壳、Obsidian/Evernote 残片等元数据样板；原文仍可完整查看，被过滤块不参与检索与 Brief。">
              <Button
                type="text"
                size="small"
                icon={<QuestionCircleOutlined />}
                aria-label="查看 Evidence 过滤说明"
              />
            </Tooltip>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            已过滤 {filteredTotal} 个元数据样板块（不影响原文查看）。
          </Text>
          <Space size={4} wrap>
            {filterSummary.rules.map((rule) => (
              <Tag key={rule.rule_id}>
                {rule.label} ×{rule.count}
              </Tag>
            ))}
          </Space>
        </div>
      ) : null}
      <div className="knowledge-jobs-origins">
        <Space size={4} align="center" className="knowledge-jobs-origins-title">
          <Title level={5}>导入记录</Title>
          <Tooltip
            title="相同内容自动复用已有 Source。重复上传相同字节时，系统会让上传结果进入已有 Source，不会创建重复 Evidence；每次导入都会追加一条 Origin 记录。"
          >
            <Button
              type="text"
              size="small"
              icon={<QuestionCircleOutlined />}
              aria-label="查看去重说明"
            />
          </Tooltip>
        </Space>
        <List
          dataSource={origins}
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
    </div>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="knowledge-status-line">
      <span className="knowledge-status-line-label">{label}</span>
      <span>{value}</span>
    </div>
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
  // KI-10：旧 Brief 存在时 processing 表示"正在重建"；outdated 表示配置已变化；
  // rebuildFailed 表示最近重建未通过但旧 Brief 已保留（Spec §10.4）。
  const isRebuilding = briefStatus === 'processing' && brief != null;
  const outdated = brief?.outdated === true && !isRebuilding;
  const rebuildFailed =
    brief != null && latestAttempt?.status === 'failed' && !!latestAttempt.error_message;

  return (
    <div className="knowledge-brief-block">
      <div className="knowledge-brief-head">
        <Title level={5} className="knowledge-brief-title">
          <span className="knowledge-brief-spark">
            <ReadOutlined />
          </span>
          Brief 导读
        </Title>
        <Space size={6} wrap>
          <Pill variant={isRebuilding || outdated || rebuildFailed ? 'amber' : 'violet'}>
            {isRebuilding ? '正在重建' : BRIEF_LABEL[briefStatus] ?? briefStatus}
          </Pill>
          <Button
            size="small"
            onClick={onRebuild}
            loading={rebuilding}
            disabled={briefStatus === 'processing'}
          >
            {brief ? '重建 Brief' : '生成 Brief'}
          </Button>
        </Space>
      </div>
      {blockReason ? (
        <Alert
          type="warning"
          showIcon
          message={`Brief 暂缓：${blockReason}`}
          description="请先在设置中配置满足 96K context 的 Provider，然后点击生成 Brief。"
        />
      ) : null}
      {outdated ? (
        <Alert
          type="warning"
          showIcon
          message="Brief 已相对当前配置过期"
          description="Provider / Prompt / Schema / Snapshot 已变化，旧 Brief 仍可查看，建议重建。"
          style={{ marginTop: 8 }}
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
      {rebuildFailed ? (
        <Alert
          type="warning"
          showIcon
          message="最近一次重建未通过，已保留旧 Brief"
          description={latestAttempt?.error_message ?? ''}
          style={{ marginTop: 8 }}
        />
      ) : null}
      {latestAttempt?.status === 'failed' &&
      (latestAttempt.validation_report.issues?.length ?? 0) > 0 ? (
        <BriefValidationIssues
          report={latestAttempt.validation_report}
          onCitationJump={onCitationJump}
        />
      ) : null}
      {showEmpty && !blockReason ? (
        <Empty description="尚未生成 Brief，可在上方点击「生成 Brief」" />
      ) : null}
      {brief ? (
        <BriefPayloadView brief={brief} onCitationJump={onCitationJump} />
      ) : null}
      <div className="knowledge-brief-footer">Source ID：{sourceId}</div>
    </div>
  );
}

// KBR-05：issue_type → 中文 label。Source 状态区只显示稳定 error code + 失败总数 +
// 短摘要；Attempt 详情按 issue_type 区分 citation/support/coverage 失败。
const ISSUE_TYPE_LABEL: Record<string, string> = {
  schema_invalid: 'Schema 非法',
  citation_missing: '引用缺失',
  citation_ownership: '引用越界',
  support_partial: '部分支持',
  support_unsupported: '未支持',
  support_contradicted: '相矛盾',
  coverage_missing: '章节未覆盖',
};

function BriefValidationIssues({
  report,
  onCitationJump,
}: {
  report: BriefValidationReport;
  onCitationJump: (evidenceId: string) => void;
}) {
  // Attempt/处理记录展示全部失败项，每项可定位到候选 Brief block 与已引用 Evidence。
  // 详情不复制 Evidence 正文，按 evidence_id 跳转到本地 Evidence。
  const issues = report.issues ?? [];
  if (issues.length === 0) {
    return null;
  }
  return (
    <Alert
      type="error"
      showIcon
      style={{ marginTop: 8 }}
      message={`Brief 质量校验失败：共 ${report.failure_count ?? issues.length} 条`}
      description={
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          {issues.map((issue, index) => (
            <div
              key={`${issue.block_path}-${index}`}
              className="knowledge-brief-issue"
            >
              <Space size={6} wrap>
                <Pill variant="rose">
                  {ISSUE_TYPE_LABEL[issue.issue_type] ?? issue.issue_type}
                </Pill>
                <Text strong>{issue.block_path || '（全局）'}</Text>
              </Space>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {issue.reason}
                </Text>
              </div>
              {issue.evidence_ids.length > 0 ? (
                <Space size={4} wrap>
                  {issue.evidence_ids.map((eid) => (
                    <Button
                      key={eid}
                      size="small"
                      type="link"
                      onClick={() => onCitationJump(eid)}
                    >
                      {eid}
                    </Button>
                  ))}
                </Space>
              ) : null}
            </div>
          ))}
        </Space>
      }
    />
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
    <div style={{ width: '100%' }}>
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
      <div className="knowledge-brief-section">
        <Title level={5} className="knowledge-brief-section-label">
          章节导读
        </Title>
        {payload.section_guides.map((item, index) => (
          <div key={`${item.section_key}-${index}`} className="knowledge-section-guide">
            <span className="knowledge-section-guide-path">
              {item.heading_path.map((segment, segmentIndex) => (
                <Fragment key={segmentIndex}>
                  {segmentIndex > 0 && (
                    <span className="knowledge-section-guide-sep">/</span>
                  )}
                  {segment}
                </Fragment>
              ))}
            </span>
            <div className="knowledge-section-guide-summary">{item.summary}</div>
            <BriefCitationChips evidenceIds={item.evidence_ids} onJump={onCitationJump} />
          </div>
        ))}
      </div>
      <BriefStatementList
        title="局限与未覆盖"
        accent="warning"
        items={payload.limitations}
        onCitationJump={onCitationJump}
      />
      {payload.coverage && payload.coverage.length > 0 ? (
        <div className="knowledge-brief-section">
          <Title level={5} className="knowledge-brief-section-label">
            章节覆盖
          </Title>
          <div className="knowledge-coverage-row">
            {payload.coverage.map((item) => (
              <span
                key={item.section_key}
                className={`knowledge-chip-coverage${
                  item.status === 'covered' ? ' is-covered' : ' is-skipped'
                }`}
              >
                {item.section_key}
                {item.status === 'skipped'
                  ? `（已跳过：${item.skipped_reason || '—'}）`
                  : ''}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BriefStatementList({
  title,
  accent,
  items,
  onCitationJump,
}: {
  title: string;
  accent?: 'warning';
  items: BriefStatement[];
  onCitationJump: (evidenceId: string) => void;
}) {
  if (!items.length) {
    return null;
  }
  return (
    <div className="knowledge-brief-section">
      <Title level={5} className="knowledge-brief-section-label">
        {title}
      </Title>
      {items.map((item, index) => (
        <div
          key={`${title}-${index}`}
          className={`knowledge-brief-statement${accent ? ` knowledge-brief-statement--${accent}` : ''}`}
        >
          <div className="knowledge-brief-statement-text">{item.statement}</div>
          <BriefCitationChips evidenceIds={item.evidence_ids} onJump={onCitationJump} />
        </div>
      ))}
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
    <div className="knowledge-citation-chips">
      {evidenceIds.map((id) => (
        <button key={id} type="button" className="knowledge-chip-cite" onClick={() => onJump(id)}>
          {id}
        </button>
      ))}
    </div>
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
      <Empty description="尚未生成 Evidence" />
    );
  }
  return (
    <div>
      <List
        className="knowledge-evidence-list"
        dataSource={evidence}
        rowKey={(item) => item.id}
        renderItem={(item) => {
          const isHighlighted = highlightEvidenceId === item.id;
          return (
            <List.Item>
              <div
                ref={isHighlighted ? highlightRef : undefined}
                className={`knowledge-evidence-item${isHighlighted ? ' is-hit' : ''}`}
              >
                <div className="knowledge-evidence-meta">
                  <span className="knowledge-evidence-kind">{item.block_kind}</span>
                  <span className="knowledge-evidence-loc">
                    行 {item.line_start}-{item.line_end} · 字符 {item.char_start}-{item.char_end}
                  </span>
                  {isHighlighted ? <Pill variant="amber">搜索命中</Pill> : null}
                </div>
                {item.heading_path.length ? (
                  <div className="knowledge-evidence-path">
                    {item.heading_path.map((segment, segmentIndex) => (
                      <Fragment key={segmentIndex}>
                        {segmentIndex > 0 && (
                          <span className="knowledge-evidence-path-sep">›</span>
                        )}
                        {segment}
                      </Fragment>
                    ))}
                  </div>
                ) : null}
                {item.kind === 'asset' && item.asset_id != null ? (
                  <AssetEvidenceView
                    sourceId={sourceId}
                    assetId={item.asset_id}
                    alt={item.search_text}
                  />
                ) : null}
                <MarkdownContent content={item.canonical_excerpt} />
                <span className="knowledge-evidence-id">{item.id}</span>
              </div>
            </List.Item>
          );
        }}
      />
    </div>
  );
}

function OriginalMarkdownBlock({
  sourceId,
  content,
  loading,
  error,
}: {
  sourceId: number;
  content: string | undefined;
  loading: boolean;
  error: boolean;
}) {
  if (loading) {
    return <Spin />;
  }
  if (error || content === undefined) {
    return (
      <Alert
        type="warning"
        showIcon
        message="无法读取原始 Markdown"
        description="可以下载原件后在本地查看。"
      />
    );
  }
  return (
    <div className="knowledge-original-markdown">
      <div className="knowledge-original-markdown-toolbar">
        <Text type="secondary">以下内容按原始 Markdown 渲染，未经过模型改写。</Text>
        <Button size="small" href={buildKnowledgeSourceContentUrl(sourceId)} target="_blank">
          下载原件
        </Button>
      </div>
      <MarkdownContent content={content} />
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="knowledge-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
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
        className="knowledge-evidence-asset"
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
      <List
        className="knowledge-jobs-list"
        dataSource={data.jobs}
        rowKey={(item) => item.id}
        renderItem={(item) => (
          <List.Item>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Space size={8} wrap>
                <span className="knowledge-evidence-kind">{item.kind}</span>
                <Pill variant={jobStatusVariant(item.status)}>
                  {JOB_STATUS_LABEL[item.status] ?? item.status}
                </Pill>
                <Text type="secondary">队列：{item.queue}</Text>
                {item.canceled ? <Pill variant="rose">已取消</Pill> : null}
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
                  <span className="knowledge-evidence-kind">{item.block_kind}</span>
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
                <span className="knowledge-evidence-id">{item.evidence_id}</span>
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
          accept=".md,.txt,text/markdown,text/plain"
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
            accept=".md,text/markdown"
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
