import { describe, expect, it } from 'vitest';
import { MATERIAL_FLOW_COPY } from './materialFlowCopy';
import { OPPORTUNITY_FIT_COPY } from './opportunityFitCopy';

const LEGACY_FIXED_PHRASES = [
  'AI recommendation',
  'Reject proposal',
  'Generate evidence-gated resume proposal',
  'No safe evidence-backed changes are available.',
  'Request failed with status code 502',
  'Evidence source',
  'Start Deep Review',
];

describe('controlled proposal copy stays localized', () => {
  it('does not reintroduce known fixed English UI phrases', () => {
    const controlledCopy = JSON.stringify({ MATERIAL_FLOW_COPY, OPPORTUNITY_FIT_COPY });

    for (const phrase of LEGACY_FIXED_PHRASES) {
      expect(controlledCopy).not.toContain(phrase);
    }
  });

  it('keeps user and evidence text outside the fixed copy mapping', () => {
    expect(MATERIAL_FLOW_COPY.proposal.empty).toContain('证据');
    expect(OPPORTUNITY_FIT_COPY.evidence.jd).toContain('岗位描述');
    expect(OPPORTUNITY_FIT_COPY.evidence.user_assertion).toContain('用户断言');
  });
});
