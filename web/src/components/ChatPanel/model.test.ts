import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '@/types/chat';
import {
  buildTurns,
  collectEvidence,
  hydrateMissingPendingAction,
  firstPendingConversationId,
  pendingActionForConversation,
  pendingComposerDisabledReason,
  reloadConversationTurns,
  toolMeta,
} from './model';

function msg(patch: Partial<ChatMessage> & Pick<ChatMessage, 'role'>): ChatMessage {
  return {
    id: patch.id ?? 1,
    conversation_id: patch.conversation_id ?? 1,
    role: patch.role,
    content: patch.content ?? '',
    tool_calls: patch.tool_calls,
    tool_call_id: patch.tool_call_id,
    created_at: patch.created_at ?? '2026-07-06T12:00:00+08:00',
  };
}

describe('buildTurns evidence normalization', () => {
  it('has localized metadata for resume match read tools', () => {
    const meta = toolMeta('list_resume_matches');

    expect(meta.kind).toBe('read');
    expect(meta.label).toBe('查看简历匹配记录');
  });

  it('has write metadata for resume v0.1 tools', () => {
    expect(toolMeta('resume_update_career_intent')).toMatchObject({
      kind: 'write',
      label: '更新简历求职意向',
    });
    expect(toolMeta('resume_rewrite_highlight')).toMatchObject({
      kind: 'write',
      label: '改写简历亮点',
    });
  });

  it('reloads stored turns for pending confirmations so current-turn evidence is available', async () => {
    const turns = await reloadConversationTurns(42, async (id) => {
      expect(id).toBe(42);
      return [
        { id: 1, conversation_id: 42, role: 'user', content: '更新启明智能 offer', created_at: '2026-01-01T00:00:00Z' },
        {
          id: 2,
          conversation_id: 42,
          role: 'assistant',
          content: '',
          tool_calls: JSON.stringify([{ id: 'call_1', function: { name: 'list_offers', arguments: '{"company_name":"启明智能"}' } }]),
          created_at: '2026-01-01T00:00:01Z',
        },
        {
          id: 3,
          conversation_id: 42,
          role: 'tool',
          content: JSON.stringify([{ id: 7, company_name: '启明智能', position_name: '算法工程师', total_cash: 1000000 }]),
          tool_call_id: 'call_1',
          created_at: '2026-01-01T00:00:02Z',
        },
        { id: 4, conversation_id: 42, role: 'assistant', content: '已找到 offer，需要确认。', created_at: '2026-01-01T00:00:03Z' },
      ];
    });

    expect(turns).not.toBeNull();
    expect(collectEvidence(turns ?? []).map((item) => item.title)).toEqual(['启明智能']);
  });

  it('keeps pending confirmation fallback available if stored turns cannot reload', async () => {
    const turns = await reloadConversationTurns(42, async () => {
      throw new Error('offline');
    });

    expect(turns).toBeNull();
  });

  it('keeps read evidence visible when the latest assistant turn is a pending write', () => {
    const turns = buildTurns([
      msg({ role: 'user', content: '把启明智能改成 offer' }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ id: 'read-app', name: 'get_application', args: { id: 7 } }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'read-app',
        content: JSON.stringify({
          id: 7,
          company_name: '启明智能',
          position_name: '算法工程师',
          status: 'interview',
          notes: '终面已结束。',
        }),
      }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([
          { id: 'write-app', name: 'update_application_status', args: { id: 7, status: 'offer' } },
        ]),
      }),
    ]);

    expect(collectEvidence(turns).map((item) => item.title)).toEqual(['启明智能']);
    expect(turns[turns.length - 1]?.steps?.map((step) => step.name)).toEqual([
      'get_application',
      'update_application_status',
    ]);
  });

  it('localizes application status details in tool step summaries', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([
          { id: 'write-app', name: 'create_application', args: { company_name: '牛客网', position_name: 'agent开发', status: 'applied' } },
        ]),
      }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'create_application',
      detail: '已投递',
    });
  });

  it('attaches application evidence from tool results to the assistant turn', () => {
    const turns = buildTurns([
      msg({ role: 'user', content: '查看投递' }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([
          {
            id: 7,
            company_name: '字节跳动',
            position_name: '后端工程师',
            status: 'interview',
            source: 'manual',
            applied_at: '2026-07-01',
          },
        ]),
      }),
      msg({ role: 'assistant', content: '你有 1 条进行中的面试。' }),
    ]);

    expect(turns[1].steps?.[0]).toMatchObject({
      name: 'list_applications',
      detail: '字节跳动',
      evidence: [
        {
          id: 'application-7',
          kind: 'application',
          title: '字节跳动',
          meta: '后端工程师 \u00b7 面试 \u00b7 2026-07-01',
          source: 'list_applications',
        },
      ],
    });
  });

  it('classifies event tool results as event evidence even when company is present', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ id: 'call-events', name: 'list_application_events', args: {} }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-events',
        content: JSON.stringify([
          {
            record_type: 'application_event',
            application_event_id: 1,
            id: 1,
            application_id: 7,
            company_name: '拼多多',
            position_name: 'agent开发',
            event_type: 'interview',
            subtype: 'technical',
            scheduled_at: '2026-07-01T07:00:00Z',
            duration_minutes: 60,
            notes: '一面',
          },
        ]),
      }),
      msg({ role: 'assistant', content: '找到 1 场面试。' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'list_application_events',
      detail: '拼多多',
      evidence: [
        {
          id: 'list_application_events-1',
          kind: 'event',
          title: '拼多多',
          meta: 'agent开发 · interview · technical · 2026-07-01T07:00:00Z',
          snippet: '一面',
          source: 'list_application_events',
        },
      ],
    });
  });

  it('attaches evidence to the final answer when a tool-calling assistant includes preamble content', () => {
    const turns = buildTurns([
      msg({ role: 'user', content: '查看投递' }),
      msg({
        role: 'assistant',
        content: '我来查一下。',
        tool_calls: JSON.stringify([{ id: 'call-apps', name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-apps',
        content: JSON.stringify([
          {
            id: 7,
            company_name: '字节跳动',
            position_name: '后端工程师',
            status: 'interview',
          },
        ]),
      }),
      msg({ role: 'assistant', content: '你有 1 条进行中的面试。' }),
    ]);

    expect(turns.map((turn) => [turn.role, turn.content, turn.steps?.length ?? 0])).toEqual([
      ['user', '查看投递', 0],
      ['assistant', '我来查一下。', 0],
      ['assistant', '你有 1 条进行中的面试。', 1],
    ]);
    expect(collectEvidence(turns).map((item) => item.title)).toEqual(['字节跳动']);
  });

  it('keeps malformed tool results as an unavailable detail instead of throwing', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'search_knowledge', args: { query: '系统设计' } }]),
      }),
      msg({ role: 'tool', content: '{bad json' }),
      msg({ role: 'assistant', content: '已搜索。' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'search_knowledge',
      detail: '系统设计',
      evidenceUnavailable: true,
    });
  });

  it('shows empty array tool results as no matching records instead of unavailable evidence', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'search_knowledge', args: { query: 'negotiation' } }]),
      }),
      msg({ role: 'tool', content: '[]' }),
      msg({ role: 'assistant', content: 'No knowledge matched.' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'search_knowledge',
      detail: 'negotiation',
      resultText: '没有匹配结果',
    });
    expect(turns[0].steps?.[0].evidenceUnavailable).toBeFalsy();
  });

  it('attaches evidence from knowledge search result payloads', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ id: 'call-knowledge', name: 'search_knowledge', args: { query: 'JVM' } }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-knowledge',
        content: JSON.stringify([
          {
            record_type: 'knowledge_search_result',
            search_result_id: 12,
            document_id: 3,
            document_title: 'JVM内存模型',
            source_name: 'manual',
            chunk_id: 12,
            chunk_index: 0,
            snippet: '堆、栈、方法区和程序计数器是常见考点。',
          },
        ]),
      }),
      msg({ role: 'assistant', content: '找到了 JVM 笔记。' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'search_knowledge',
      detail: 'JVM内存模型',
      evidence: [
        {
          id: 'search_knowledge-12',
          kind: 'knowledge',
          title: 'JVM内存模型',
          meta: 'manual',
          snippet: '堆、栈、方法区和程序计数器是常见考点。',
          source: 'search_knowledge',
        },
      ],
    });
    expect(turns[0].steps?.[0].evidenceUnavailable).toBeFalsy();
  });

  it('keeps knowledge document contents as compact previews in tool evidence', () => {
    const longContent = [
      '# Java Threads',
      'Processes isolate memory while threads share process resources.',
      'Thread creation can use Thread, Runnable, Callable, or a thread pool.',
      'This sentence should not be visible in the process timeline preview.',
    ].join('\n\n');

    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ id: 'call-doc', name: 'get_knowledge_document', args: { id: 8 } }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-doc',
        content: JSON.stringify({
          record_type: 'knowledge_document',
          knowledge_document_id: 8,
          id: 8,
          title: 'Java Threads',
          content: longContent,
        }),
      }),
      msg({ role: 'assistant', content: 'I checked the document.' }),
    ]);

    const snippet = turns[0].steps?.[0].evidence?.[0].snippet ?? '';
    expect(snippet.length).toBeLessThanOrEqual(180);
    expect(snippet).toContain('Processes isolate memory');
    expect(snippet).not.toContain('This sentence should not be visible');
  });

  it('classifies resume tool results as resume evidence', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ id: 'call-resume', name: 'list_resumes', args: {} }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-resume',
        content: JSON.stringify([
          {
            record_type: 'resume',
            resume_id: 6,
            id: 6,
            name: '后端简历',
            parse_status: 'text-ready',
            parsed_data: 'Java Spring Boot 高并发项目经验',
          },
        ]),
      }),
      msg({ role: 'assistant', content: '找到了简历。' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'list_resumes',
      detail: '后端简历',
      evidence: [
        {
          id: 'list_resumes-6',
          kind: 'resume',
          title: '后端简历',
          meta: 'text-ready',
          snippet: 'Java Spring Boot 高并发项目经验',
          source: 'list_resumes',
        },
      ],
    });
  });

  it('classifies resume match results as match evidence instead of generic resume evidence', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ id: 'call-match', name: 'list_resume_matches', args: { resume_id: 6 } }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-match',
        content: JSON.stringify([
          {
            record_type: 'resume_match',
            resume_match_id: 9,
            id: 9,
            resume_id: 6,
            application_id: 7,
            jd_text: '后端开发工程师，负责高并发交易系统',
            result: '{"summary":"匹配度较高，后端项目经验契合"}',
          },
        ]),
      }),
      msg({ role: 'assistant', content: '找到了简历匹配结果。' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'list_resume_matches',
      detail: '简历匹配 #9',
      evidence: [
        {
          id: 'list_resume_matches-9',
          kind: 'resume',
          title: '简历匹配 #9',
          meta: '简历 #6 · 投递 #7',
          snippet: '匹配度较高，后端项目经验契合',
          source: 'list_resume_matches',
        },
      ],
    });
  });

  it('attaches evidence from JD analysis payloads', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ id: 'call-jd', name: 'list_jd_analyses', args: {} }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-jd',
        content: JSON.stringify([
          {
            record_type: 'jd_analysis',
            jd_analysis_id: 2,
            id: 2,
            application_id: 7,
            jd_source: 'text',
            jd_text: '后端开发工程师，负责高并发交易系统',
            result: '{"summary":"高并发后端岗位，重点关注 Java、缓存和分布式系统"}',
          },
        ]),
      }),
      msg({ role: 'assistant', content: '找到了 JD 分析。' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'list_jd_analyses',
      detail: 'JD 分析 #2',
      evidence: [
        {
          id: 'list_jd_analyses-2',
          kind: 'jd',
          title: 'JD 分析 #2',
          meta: 'text · 投递 #7',
          snippet: '高并发后端岗位，重点关注 Java、缓存和分布式系统',
          source: 'list_jd_analyses',
        },
      ],
    });
    expect(turns[0].steps?.[0].evidenceUnavailable).toBeFalsy();
  });

  it('matches multiple tool results to the correct tool call id', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([
          { id: 'call-apps', name: 'list_applications', args: {} },
          { id: 'call-knowledge', name: 'search_knowledge', args: { query: '系统设计' } },
        ]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-knowledge',
        content: JSON.stringify([{ id: 10, title: '系统设计', summary: '模式' }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-apps',
        content: JSON.stringify([{ id: 7, company_name: '字节跳动', position_name: '后端工程师' }]),
      }),
      msg({ role: 'assistant', content: '都找到了。' }),
    ]);

    expect(turns[0].steps?.map((step) => [step.name, step.detail])).toEqual([
      ['list_applications', '字节跳动'],
      ['search_knowledge', '系统设计'],
    ]);
    expect(turns[0].steps?.[0].evidence?.[0]).toMatchObject({
      id: 'application-7',
      source: 'list_applications',
      title: '字节跳动',
    });
    expect(turns[0].steps?.[1].evidence?.[0]).toMatchObject({
      id: 'search_knowledge-10',
      source: 'search_knowledge',
      title: '系统设计',
    });
  });

  it('maps legacy tool results to pending steps in result order when ids are missing', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([
          { name: 'list_applications', args: {} },
          { name: 'search_knowledge', args: { query: '系统设计' } },
        ]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 7, company_name: '字节跳动', position_name: '后端工程师' }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 10, title: '系统设计', summary: '模式' }]),
      }),
      msg({ role: 'assistant', content: '都找到了。' }),
    ]);

    expect(turns[0].steps?.map((step) => [step.name, step.detail])).toEqual([
      ['list_applications', '字节跳动'],
      ['search_knowledge', '系统设计'],
    ]);
  });

  it('maps missing-id results to the next unfilled step after id-based results', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([
          { id: 'call-apps', name: 'list_applications', args: {} },
          { id: 'call-knowledge', name: 'search_knowledge', args: { query: '系统设计' } },
        ]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-apps',
        content: JSON.stringify([{ id: 7, company_name: '字节跳动', position_name: '后端工程师' }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 10, title: '系统设计', summary: '模式' }]),
      }),
      msg({ role: 'assistant', content: '都找到了。' }),
    ]);

    expect(turns[0].steps?.map((step) => [step.name, step.detail])).toEqual([
      ['list_applications', '字节跳动'],
      ['search_knowledge', '系统设计'],
    ]);
    expect(turns[0].steps?.[0].evidence?.[0]).toMatchObject({
      id: 'application-7',
      title: '字节跳动',
    });
    expect(turns[0].steps?.[1].evidence?.[0]).toMatchObject({
      id: 'search_knowledge-10',
      title: '系统设计',
    });
  });

  it('does not overwrite id-matched empty evidence results with later fallback results', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([
          { id: 'call-note', name: 'search_knowledge', args: { query: '缺失来源' } },
          { id: 'call-apps', name: 'list_applications', args: {} },
        ]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-note',
        content: JSON.stringify({ ok: true }),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 7, company_name: '字节跳动', position_name: '后端工程师' }]),
      }),
      msg({ role: 'assistant', content: '找到 1 条投递。' }),
    ]);

    expect(turns[0].steps?.map((step) => [step.name, step.detail])).toEqual([
      ['search_knowledge', '缺失来源'],
      ['list_applications', '字节跳动'],
    ]);
    expect(turns[0].steps?.[0].evidence).toBeUndefined();
    expect(turns[0].steps?.[1].evidence?.[0]).toMatchObject({
      id: 'application-7',
      title: '字节跳动',
    });
  });

  it('aggregates newest evidence first across visible turns', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_offers', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 3, company_name: '启明智能', position_name: '产品经理', total_cash: 600000 }]),
      }),
      msg({ role: 'assistant', content: '找到了 offer。' }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 4, company_name: '星河智能', position_name: '产品经理', status: 'applied' }]),
      }),
      msg({ role: 'assistant', content: '找到了投递。' }),
    ]);

    expect(collectEvidence(turns).map((item) => item.title)).toEqual(['星河智能', '启明智能']);
  });

  it('preserves backend evidence order within a single tool result', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([
          { id: 5, company_name: '启明智能', position_name: '产品经理', status: 'interview' },
          { id: 4, company_name: '星河智能', position_name: '产品经理', status: 'applied' },
        ]),
      }),
      msg({ role: 'assistant', content: '找到了多条投递。' }),
    ]);

    expect(collectEvidence(turns).map((item) => item.title)).toEqual(['启明智能', '星河智能']);
  });

  it('keeps plain-text tool errors visible in the process timeline data', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ id: 'call-app', name: 'get_application', args: {} }]),
      }),
      msg({ role: 'tool', tool_call_id: 'call-app', content: "错误：'id'" }),
      msg({ role: 'assistant', content: 'I could not load it.' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'get_application',
      resultText: "错误：'id'",
    });
    expect(turns[0].steps?.[0].evidenceUnavailable).toBeFalsy();
  });

  it('returns the persisted pending action for a selected conversation', () => {
    const pending = pendingActionForConversation(
      [
        {
          id: 42,
          title: 'Offer',
          context_type: 'workspace',
          context_ref: '',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          pending_action: {
            tool_name: 'update_application_status',
            human: '更新状态',
            args: { id: 1, status: 'offer' },
          },
        },
      ],
      42,
    );

    expect(pending).toEqual({
      tool_name: 'update_application_status',
      human: '更新状态',
      args: { id: 1, status: 'offer' },
    });
  });

  it('explains the next step while a chained write confirmation is pending', () => {
    expect(
      pendingComposerDisabledReason({
        tool_name: 'create_application',
        human: '新建投递：牛客网 - 软件测试工程师',
        workflow: {
          current_step: 1,
          total_steps: 2,
          current_label: '新建投递',
          next_label: '保存面试复盘',
        },
      }),
    ).toBe('请先确认“新建投递”，确认后我会继续保存面试复盘。');
  });

  it('hydrates a missing pending action for the active conversation after refresh', () => {
    const persisted = {
      tool_name: 'create_application',
      human: '新建投递：牛客网 - 软件测试工程师',
      args: { company_name: '牛客网', position_name: '软件测试工程师', status: 'interview' },
    };

    const pending = hydrateMissingPendingAction(
      null,
      [
        {
          id: 65,
          title: '牛客网面试复盘',
          context_type: 'workspace',
          context_ref: '',
          created_at: '2026-07-09T00:00:00Z',
          updated_at: '2026-07-09T00:00:01Z',
          pending_action: persisted,
        },
      ],
      65,
    );

    expect(pending).toEqual(persisted);
  });

  it('keeps the current pending action while conversation refresh is stale', () => {
    const current = {
      tool_name: 'create_application_event',
      human: '新建投递事件',
      args: { application_id: 40, event_type: 'written_test' },
    };

    const pending = hydrateMissingPendingAction(
      current,
      [
        {
          id: 65,
          title: '牛客网面试复盘',
          context_type: 'workspace',
          context_ref: '',
          created_at: '2026-07-09T00:00:00Z',
          updated_at: '2026-07-09T00:00:01Z',
          pending_action: {
            tool_name: 'create_application',
            human: '新建投递：牛客网 - 软件测试工程师',
            args: { company_name: '牛客网', position_name: '软件测试工程师' },
          },
        },
      ],
      65,
    );

    expect(pending).toEqual(current);
  });

  it('finds the newest conversation with a pending action', () => {
    const id = firstPendingConversationId([
      {
        id: 72,
        title: '牛客网面试复盘',
        context_type: 'workspace',
        context_ref: '',
        created_at: '2026-07-09T00:00:00Z',
        updated_at: '2026-07-09T00:00:02Z',
        pending_action: {
          tool_name: 'create_application',
          human: '新建投递：牛客网 - 软件测试工程师',
          args: { company_name: '牛客网', position_name: '软件测试工程师' },
        },
      },
      {
        id: 71,
        title: '普通对话',
        context_type: 'workspace',
        context_ref: '',
        created_at: '2026-07-09T00:00:00Z',
        updated_at: '2026-07-09T00:00:01Z',
        pending_action: null,
      },
    ]);

    expect(id).toBe(72);
  });
});
