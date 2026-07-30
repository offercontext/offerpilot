import { describe, expect, it } from 'vitest';
import source from './ApplicationDetail.tsx?raw';

describe('ApplicationDetail control polish', () => {
  it('uses the shared current-source label without changing action handlers', () => {
    expect(source).toContain("<SourceStateTag state=\"current\" detail=\"当前投递\" />");
    expect(source).toContain('onOpenPilotOpportunityFit(application)');
    expect(source).toContain('setMaterialKitOpen(true)');
  });
});
