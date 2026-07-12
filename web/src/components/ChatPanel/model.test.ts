import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '@/types/chat';
import {
  buildTurns,
  collectEvidence,
  parseTurnPresentation,
  pendingActionForConversation,
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
        { id: 1, conversation_id: 42, role: 'user', content: 'Update my OpenAI offer', created_at: '2026-01-01T00:00:00Z' },
        {
          id: 2,
          conversation_id: 42,
          role: 'assistant',
          content: '',
          tool_calls: JSON.stringify([{ id: 'call_1', function: { name: 'list_offers', arguments: '{"company_name":"OpenAI"}' } }]),
          created_at: '2026-01-01T00:00:01Z',
        },
        {
          id: 3,
          conversation_id: 42,
          role: 'tool',
          content: JSON.stringify([{ id: 7, company_name: 'OpenAI', position_name: 'Research Engineer', total_cash: 1000000 }]),
          tool_call_id: 'call_1',
          created_at: '2026-01-01T00:00:02Z',
        },
        { id: 4, conversation_id: 42, role: 'assistant', content: 'I found the offer and need confirmation.', created_at: '2026-01-01T00:00:03Z' },
      ];
    });

    expect(turns).not.toBeNull();
    expect(collectEvidence(turns ?? []).map((item) => item.title)).toEqual(['OpenAI']);
  });

  it('keeps pending confirmation fallback available if stored turns cannot reload', async () => {
    const turns = await reloadConversationTurns(42, async () => {
      throw new Error('offline');
    });

    expect(turns).toBeNull();
  });

  it('attaches application evidence from tool results to the assistant turn', () => {
    const turns = buildTurns([
      msg({ role: 'user', content: 'show apps' }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([
          {
            id: 7,
            company_name: 'ByteDance',
            position_name: 'Backend Engineer',
            status: 'interview',
            source: 'manual',
            applied_at: '2026-07-01',
          },
        ]),
      }),
      msg({ role: 'assistant', content: 'You have one active interview.' }),
    ]);

    expect(turns[1].steps?.[0]).toMatchObject({
      name: 'list_applications',
      detail: 'ByteDance',
      evidence: [
        {
          id: 'application-7',
          kind: 'application',
          title: 'ByteDance',
          meta: 'Backend Engineer \u00b7 interview \u00b7 2026-07-01',
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
      msg({ role: 'assistant', content: 'I found one interview.' }),
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
      msg({ role: 'user', content: 'show apps' }),
      msg({
        role: 'assistant',
        content: 'I can look that up.',
        tool_calls: JSON.stringify([{ id: 'call-apps', name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-apps',
        content: JSON.stringify([
          {
            id: 7,
            company_name: 'ByteDance',
            position_name: 'Backend Engineer',
            status: 'interview',
          },
        ]),
      }),
      msg({ role: 'assistant', content: 'You have one active interview.' }),
    ]);

    expect(turns.map((turn) => [turn.role, turn.content, turn.steps?.length ?? 0])).toEqual([
      ['user', 'show apps', 0],
      ['assistant', 'I can look that up.', 0],
      ['assistant', 'You have one active interview.', 1],
    ]);
    expect(collectEvidence(turns).map((item) => item.title)).toEqual(['ByteDance']);
  });

  it('keeps malformed tool results as an unavailable detail instead of throwing', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'search_knowledge', args: { query: 'system design' } }]),
      }),
      msg({ role: 'tool', content: '{bad json' }),
      msg({ role: 'assistant', content: 'I searched.' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'search_knowledge',
      detail: 'system design',
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
      msg({ role: 'assistant', content: 'I found JVM notes.' }),
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
      msg({ role: 'assistant', content: 'I found a resume.' }),
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
      msg({ role: 'assistant', content: 'I found a resume match.' }),
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
      msg({ role: 'assistant', content: 'I found a JD analysis.' }),
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
          { id: 'call-knowledge', name: 'search_knowledge', args: { query: 'system design' } },
        ]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-knowledge',
        content: JSON.stringify([{ id: 10, title: 'System Design', summary: 'Patterns' }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-apps',
        content: JSON.stringify([{ id: 7, company_name: 'ByteDance', position_name: 'Backend Engineer' }]),
      }),
      msg({ role: 'assistant', content: 'I found both.' }),
    ]);

    expect(turns[0].steps?.map((step) => [step.name, step.detail])).toEqual([
      ['list_applications', 'ByteDance'],
      ['search_knowledge', 'System Design'],
    ]);
    expect(turns[0].steps?.[0].evidence?.[0]).toMatchObject({
      id: 'application-7',
      source: 'list_applications',
      title: 'ByteDance',
    });
    expect(turns[0].steps?.[1].evidence?.[0]).toMatchObject({
      id: 'search_knowledge-10',
      source: 'search_knowledge',
      title: 'System Design',
    });
  });

  it('maps legacy tool results to pending steps in result order when ids are missing', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([
          { name: 'list_applications', args: {} },
          { name: 'search_knowledge', args: { query: 'system design' } },
        ]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 7, company_name: 'ByteDance', position_name: 'Backend Engineer' }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 10, title: 'System Design', summary: 'Patterns' }]),
      }),
      msg({ role: 'assistant', content: 'I found both.' }),
    ]);

    expect(turns[0].steps?.map((step) => [step.name, step.detail])).toEqual([
      ['list_applications', 'ByteDance'],
      ['search_knowledge', 'System Design'],
    ]);
  });

  it('maps missing-id results to the next unfilled step after id-based results', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([
          { id: 'call-apps', name: 'list_applications', args: {} },
          { id: 'call-knowledge', name: 'search_knowledge', args: { query: 'system design' } },
        ]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-apps',
        content: JSON.stringify([{ id: 7, company_name: 'ByteDance', position_name: 'Backend Engineer' }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 10, title: 'System Design', summary: 'Patterns' }]),
      }),
      msg({ role: 'assistant', content: 'I found both.' }),
    ]);

    expect(turns[0].steps?.map((step) => [step.name, step.detail])).toEqual([
      ['list_applications', 'ByteDance'],
      ['search_knowledge', 'System Design'],
    ]);
    expect(turns[0].steps?.[0].evidence?.[0]).toMatchObject({
      id: 'application-7',
      title: 'ByteDance',
    });
    expect(turns[0].steps?.[1].evidence?.[0]).toMatchObject({
      id: 'search_knowledge-10',
      title: 'System Design',
    });
  });

  it('does not overwrite id-matched empty evidence results with later fallback results', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([
          { id: 'call-note', name: 'search_knowledge', args: { query: 'missing source' } },
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
        content: JSON.stringify([{ id: 7, company_name: 'ByteDance', position_name: 'Backend Engineer' }]),
      }),
      msg({ role: 'assistant', content: 'I found one application.' }),
    ]);

    expect(turns[0].steps?.map((step) => [step.name, step.detail])).toEqual([
      ['search_knowledge', 'missing source'],
      ['list_applications', 'ByteDance'],
    ]);
    expect(turns[0].steps?.[0].evidence).toBeUndefined();
    expect(turns[0].steps?.[1].evidence?.[0]).toMatchObject({
      id: 'application-7',
      title: 'ByteDance',
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
        content: JSON.stringify([{ id: 3, company_name: 'OpenAI', position_name: 'PM', total_cash: 600000 }]),
      }),
      msg({ role: 'assistant', content: 'Offer found.' }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 4, company_name: 'Anthropic', position_name: 'PM', status: 'applied' }]),
      }),
      msg({ role: 'assistant', content: 'Application found.' }),
    ]);

    expect(collectEvidence(turns).map((item) => item.title)).toEqual(['Anthropic', 'OpenAI']);
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
          { id: 5, company_name: 'OpenAI', position_name: 'PM', status: 'interview' },
          { id: 4, company_name: 'Anthropic', position_name: 'PM', status: 'applied' },
        ]),
      }),
      msg({ role: 'assistant', content: 'Applications found.' }),
    ]);

    expect(collectEvidence(turns).map((item) => item.title)).toEqual(['OpenAI', 'Anthropic']);
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
});

describe('Pilot turn presentation reconstruction', () => {
  it('parses persisted markdown headings and preserves leading detail markdown', () => {
    const presentation = parseTurnPresentation([
      '# 投递进展',
      '',
      '已核对 **两个**岗位的状态。',
      '',
      '   ## 结论',
      '',
      '优先准备下一轮技术面。',
      '',
      '### 下一步',
      '',
      '-  整理项目亮点  ',
      '- 联系招聘方确认时间',
    ].join('\n'));

    expect(presentation).toEqual({
      conclusion: '优先准备下一轮技术面。',
      actions: ['整理项目亮点', '联系招聘方确认时间'],
      detailMarkdown: '# 投递进展\n\n已核对 **两个**岗位的状态。',
    });
  });

  it('falls back for incomplete or reversed presentation headings', () => {
    const onlyConclusion = '## 结论\n\n继续跟进。';
    const noAction = '## 结论\n\n继续跟进。\n\n## 下一步\n\n稍后处理。';
    const reversed = '## 下一步\n\n- 跟进\n\n## 结论\n\n继续跟进。';

    expect(parseTurnPresentation(onlyConclusion)).toBeUndefined();
    expect(parseTurnPresentation(noAction)).toBeUndefined();
    expect(parseTurnPresentation(reversed)).toBeUndefined();

    const turns = buildTurns([msg({ role: 'assistant', content: noAction })]);
    expect(turns[0]).toMatchObject({
      content: noAction,
      taskTitle: '本轮任务',
      presentation: undefined,
    });
  });

  it('keeps at most the first three actionable bullets', () => {
    const presentation = parseTurnPresentation([
      '## 结论',
      '',
      '可以推进。',
      '',
      '## 下一步',
      '',
      '* 第一项',
      '+ 第二项',
      '- 第三项',
      '- 第四项',
    ].join('\n'));

    expect(presentation?.actions).toEqual(['第一项', '第二项', '第三项']);
  });

  it('attaches real tool steps and structured presentation to the final assistant turn', () => {
    const turns = buildTurns([
      msg({
        role: 'user',
        content: '   Review    application  pipeline and prepare an exceptionally detailed final summary today  ',
      }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ id: 'call-apps', name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        tool_call_id: 'call-apps',
        content: JSON.stringify([{ id: 7, company_name: 'OpenAI', position_name: 'Engineer' }]),
      }),
      msg({
        role: 'assistant',
        content: [
          '已查到投递记录。',
          '',
          '## 结论',
          '',
          '应优先准备 OpenAI 面试。',
          '',
          '## 下一步',
          '',
          '- 更新项目案例',
          '- 安排模拟面试',
        ].join('\n'),
      }),
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[1]).toMatchObject({
      role: 'assistant',
      content: '已查到投递记录。',
      taskTitle: 'Review application pipeline and pre…',
      presentation: {
        conclusion: '应优先准备 OpenAI 面试。',
        actions: ['更新项目案例', '安排模拟面试'],
        detailMarkdown: '已查到投递记录。',
      },
      steps: [
        {
          name: 'list_applications',
          toolCallId: 'call-apps',
        },
      ],
    });
    expect(turns[1].steps).toHaveLength(1);
    expect(turns[1].taskTitle).toHaveLength(36);
  });
});
