import { describe, expect, it } from 'vitest';
import source from './knowledge.ts?raw';

describe('knowledge service KI-03 contract', () => {
  it('exposes upload/paste/list/detail/evidence/search endpoints without legacy wiki helpers', () => {
    expect(source).toContain('/knowledge/sources');
    expect(source).toContain('/knowledge/evidence/search');
    expect(source).toContain('/knowledge/sources/');
    expect(source).toContain('uploadKnowledgeSource');
    expect(source).toContain('pasteKnowledgeSource');
    expect(source).toContain('searchKnowledgeEvidence');
    expect(source).toContain('buildKnowledgeSourceContentUrl');
    expect(source).not.toContain('fetchKnowledgePages');
    expect(source).not.toContain('searchWiki');
    expect(source).not.toContain('addToWiki');
  });
});

describe('knowledge service KI-04 contract', () => {
  it('exposes bundle upload and asset download endpoints', () => {
    expect(source).toContain('uploadKnowledgeBundle');
    expect(source).toContain('fetchKnowledgeSourceAssets');
    expect(source).toContain('buildKnowledgeAssetContentUrl');
    expect(source).toContain('/assets/');
    expect(source).toContain('assets/${assetId}/content');
  });
});
