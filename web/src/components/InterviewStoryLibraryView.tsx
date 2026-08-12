import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Empty, Input, List, Space, Spin, Tag, Typography } from 'antd';
import { archiveInterviewStory, getInterviewStory, getInterviewStoryVersion, listInterviewStories, listInterviewStoryVersions, restoreInterviewStory } from '@/services/interviewStories';
import type { InterviewStory, InterviewStoryVersion } from '@/types/interviewStory';

const { Paragraph, Title, Text } = Typography;

export interface InterviewStoryOpenDraft {
  entrypoint: 'ui' | 'pilot';
  reviewNoteId?: number;
  targetStoryId?: number;
  expectedCurrentVersionId?: number;
  expectedStoryRevision?: number;
}

interface Props {
  onOpenDraft: (input: InterviewStoryOpenDraft) => void;
  onBack?: () => void;
}

function sourceStateLabel(story: InterviewStory): string | null {
  if (story.source_states.some((item) => item.state === 'changed')) return '来源已变化';
  if (story.source_states.some((item) => item.state === 'missing')) return '部分来源缺失';
  if (story.source_states.length > 0) return '保留冻结来源';
  return null;
}

function hasFrozenUserAssertion(story: InterviewStory): boolean {
  return story.source_states.some((item) => item.state === 'frozen_user_assertion');
}

export default function InterviewStoryLibraryView({ onOpenDraft, onBack }: Props) {
  const [stories, setStories] = useState<InterviewStory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [status, setStatus] = useState<'active' | 'archived'>('active');
  const [query, setQuery] = useState('');
  const [selectedStory, setSelectedStory] = useState<InterviewStory | null>(null);
  const [versions, setVersions] = useState<Array<Pick<InterviewStoryVersion, 'id' | 'version_number' | 'origin_kind' | 'confirmed_at' | 'source_fingerprint'>>>([]);
  const [selectedVersion, setSelectedVersion] = useState<InterviewStoryVersion | null>(null);
  const historyRequestGeneration = useRef(0);

  const load = (nextStatus = status, nextQuery = query) => {
    setLoading(true);
    setError(false);
    void listInterviewStories(nextStatus, nextQuery).then(setStories).catch(() => setError(true)).finally(() => setLoading(false));
  };

  useEffect(() => { load(status, query); }, [status, query]);

  const toggleArchive = async (story: InterviewStory) => {
    try {
      const updated = story.status === 'active'
        ? await archiveInterviewStory(story.id, story.story_revision)
        : await restoreInterviewStory(story.id, story.story_revision);
      setStories((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch {
      setError(true);
    }
  };

  const openStory = async (storyId: number) => {
    const generation = ++historyRequestGeneration.current;
    try {
      const [story, history] = await Promise.all([getInterviewStory(storyId), listInterviewStoryVersions(storyId)]);
      if (generation !== historyRequestGeneration.current) return;
      setSelectedStory(story);
      setVersions(history);
      setSelectedVersion(story.version ?? null);
    } catch {
      setError(true);
    }
  };

  const openVersion = async (storyId: number, versionId: number) => {
    const generation = ++historyRequestGeneration.current;
    try {
      const version = await getInterviewStoryVersion(storyId, versionId);
      if (generation !== historyRequestGeneration.current) return;
      setSelectedVersion(version);
    } catch {
      setError(true);
    }
  };

  return (
    <section style={{ padding: 24, maxWidth: 1040, margin: '0 auto' }} aria-label="面试故事库">
      <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 20 }}>
        <Space wrap style={{ justifyContent: 'space-between', width: '100%' }}>
          <Title level={3} style={{ margin: 0 }}>面试故事库</Title>
          <Space>
            {onBack ? <Button onClick={onBack}>返回面试</Button> : null}
            <Button type="primary" onClick={() => onOpenDraft({ entrypoint: 'ui', reviewNoteId: undefined })}>新建故事</Button>
          </Space>
        </Space>
        <Paragraph type="secondary" style={{ margin: 0 }}>
          只在你选择原始证据并确认后保存；故事版本会保留当时的来源，不会写入知识库或自动用于面试。
        </Paragraph>
        <Space wrap>
          <Button type={status === 'active' ? 'primary' : 'default'} onClick={() => setStatus('active')}>使用中</Button>
          <Button type={status === 'archived' ? 'primary' : 'default'} onClick={() => setStatus('archived')}>已归档</Button>
          <Input.Search aria-label="搜索面试故事" value={query} onChange={(event) => setQuery(event.target.value)} onSearch={(value) => setQuery(value)} placeholder="搜索故事标题" style={{ width: 260 }} />
        </Space>
      </Space>
      {loading ? <Spin aria-label="正在加载面试故事" /> : null}
      {error ? <Alert type="error" showIcon message="故事库暂时无法加载，请稍后重试。" action={<Button size="small" onClick={() => load()}>重试</Button>} /> : null}
      {!loading && !error && stories.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有已确认的面试故事" /> : null}
      {!loading && !error && stories.length > 0 ? (
        <List
          dataSource={stories}
          renderItem={(story) => {
            const state = sourceStateLabel(story);
            const assertion = hasFrozenUserAssertion(story);
            return (
              <List.Item actions={[
                <Button key="view" type="link" onClick={() => void openStory(story.id)}>查看版本</Button>,
                <Button key="archive" type="link" onClick={() => void toggleArchive(story)}>
                  {story.status === 'active' ? '归档' : '恢复'}
                </Button>,
              ]}>
                <List.Item.Meta
                  title={<Space><Text strong>{story.title}</Text><Tag>{story.status === 'active' ? '使用中' : '已归档'}</Tag></Space>}
                  description={<Space wrap><span>版本 {story.version_number ?? 0}</span>{state ? <Tag color={state === '来源已变化' ? 'warning' : 'default'}>{state}</Tag> : null}{assertion ? <Tag>包含已冻结的用户确认陈述</Tag> : null}</Space>}
                />
              </List.Item>
            );
          }}
        />
      ) : null}
      {selectedStory && selectedVersion ? (
        <section style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--op-border, #e5e7eb)' }} aria-label="故事版本历史">
          <Space style={{ justifyContent: 'space-between', width: '100%' }}>
            <Title level={4} style={{ margin: 0 }}>版本 {selectedVersion.version_number} · 已确认历史</Title>
            <Space>
              {selectedStory.status === 'active' && selectedStory.current_version_id ? (
                <Button onClick={() => onOpenDraft({
                  entrypoint: 'ui',
                  targetStoryId: selectedStory.id,
                  expectedCurrentVersionId: selectedStory.current_version_id ?? undefined,
                  expectedStoryRevision: selectedStory.story_revision,
                })}>基于此故事新建版本</Button>
              ) : null}
              <Button onClick={() => { historyRequestGeneration.current += 1; setSelectedStory(null); setSelectedVersion(null); setVersions([]); }}>关闭历史</Button>
            </Space>
          </Space>
          <List
            size="small"
            dataSource={versions}
            renderItem={(version) => <List.Item actions={[
              <Button key="version" type="link" onClick={() => void openVersion(selectedStory.id, version.id)}>查看版本 {version.version_number}</Button>,
            ]}>
              <Space><span>版本 {version.version_number}</span><Tag>{version.origin_kind === 'manual' ? '手动保存' : 'AI 建议后确认'}</Tag></Space>
            </List.Item>}
          />
          {selectedVersion.source_states.some((item) => item.state === 'changed' || item.state === 'missing') ? (
            <Alert type="warning" showIcon message="当前来源已变化，以下内容仍是当时确认的冻结版本。" style={{ marginTop: 12 }} />
          ) : <Alert type="info" showIcon message="以下内容来自已确认的冻结版本。" style={{ marginTop: 12 }} />}
          <Title level={5}>{selectedVersion.content.title.text}</Title>
          {selectedVersion.content.blocks.map((block) => <Paragraph key={block.id}>{block.text}</Paragraph>)}
          <Space wrap>
            {selectedVersion.evidence_links.map((link) => (
              <Tag key={`${link.target_kind}-${link.target_id}-${link.source_stable_id}`}>
                {link.source_kind === 'user_assertion' ? '已冻结的用户确认陈述 · ' : '证据 · '}{link.excerpt}
              </Tag>
            ))}
          </Space>
        </section>
      ) : null}
    </section>
  );
}
