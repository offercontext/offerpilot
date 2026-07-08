import { describe, expect, it } from 'vitest';
import source from './chat.ts?raw';

describe('settings service v0.1 contract', () => {
  it('exposes provider testing, fallback provider, and safe backup endpoints', () => {
    expect(source).toContain('fallback_provider_id');
    expect(source).toContain('/settings/providers/test');
    expect(source).toContain('/settings/backup');
    expect(source).toContain('testProviderConnection');
    expect(source).toContain('getSettingsBackup');
    expect(source).not.toContain('api_key: string;');
  });
});
