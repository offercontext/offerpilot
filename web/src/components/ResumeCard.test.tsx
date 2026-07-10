import { renderToStaticMarkup } from 'react-dom/server';
import { App as AntApp } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import ResumeCard from './ResumeCard';
import type { Resume } from '@/types/resume';

const Card = ResumeCard as React.ComponentType<any>;

function renderCard(resume: Resume) {
  return renderToStaticMarkup(
    <AntApp>
      <Card
        resume={resume}
        onEdit={vi.fn()}
        onSetMaster={vi.fn()}
        onCopy={vi.fn()}
        onDelete={vi.fn()}
      />
    </AntApp>
  );
}

describe('ResumeCard v0.1', () => {
  it('renders structured resume metadata and excludes match/download/export actions', () => {
    const markup = renderCard({
      id: 7,
      name: 'legacy-name',
      file_path: '',
      parsed_data: 'legacy text',
      parse_status: 'structured-ready',
      title: '后端主简历',
      is_master: true,
      parent_resume_id: null,
      source: 'dialog',
      source_file_path: '',
      content_json: {
        career_intent: { target_roles: ['Backend Engineer'] },
        contact: { name: 'Ada' },
      },
      deleted_at: null,
      created_at: '2026-07-08T02:03:00Z',
      completion_percent: 67,
      missing_sections: ['career_intent', 'projects'],
      is_complete: false,
    } as Resume);

    expect(markup).toContain('后端主简历');
    expect(markup).toContain('主简历');
    expect(markup).toContain('Pilot 对话');
    expect(markup).toContain('67%');
    expect(markup).toContain('求职意向');
    expect(markup).toContain('项目经历');
    expect(markup).toContain('创建于');
    expect(markup).toContain('编辑');
    expect(markup).toContain('复制');
    expect(markup).toContain('主简历不可删除');
    expect(markup).not.toContain('匹配');
    expect(markup).not.toContain('下载');
    expect(markup).not.toContain('导出');
  });

  it('shows set-as-master only for non-master resumes', () => {
    const markup = renderCard({
      id: 8,
      name: '',
      file_path: '',
      parsed_data: '',
      parse_status: 'structured-ready',
      title: '前端样例简历',
      is_master: false,
      parent_resume_id: 7,
      source: 'sample',
      source_file_path: '',
      content_json: {},
      deleted_at: null,
      created_at: '2026-07-08T04:00:00Z',
      completion_percent: 33,
      missing_sections: ['education'],
      is_complete: false,
    } as Resume);

    expect(markup).toContain('设为主简历');
    expect(markup).not.toContain('主简历不可删除');
  });
});
