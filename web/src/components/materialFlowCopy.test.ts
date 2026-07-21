import { describe, expect, it } from 'vitest';
import { materialFlowErrorMessage } from './materialFlowCopy';

describe('material flow error copy', () => {
  it('uses a neutral message for a general HTTP 409', () => {
    expect(materialFlowErrorMessage({ response: { status: 409 } }, 'general'))
      .toBe('操作未完成，请稍后重试');
  });

  it('distinguishes an unclassified 502 from an unverifiable proposal', () => {
    expect(materialFlowErrorMessage({ response: { status: 502 } }, 'proposal'))
      .toBe('AI 服务暂不可用，请稍后重试');
    expect(materialFlowErrorMessage({
      response: { status: 502, data: { error_code: 'material_proposal_unverifiable' } },
    }, 'proposal'))
      .toBe('AI 输出未通过证据校验，已保护原简历且未创建草稿，请重试');
  });
});
