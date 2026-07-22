import { describe, expect, it } from 'vitest';
import { createMaterialKitHandoffStore } from './materialKitHandoff';

const handoff = {
  applicationId: 7,
  resumeId: 11,
  jdText: 'Frozen JD',
};

describe('materialKitHandoffStore', () => {
  it('matches the application, freezes a minimal copy, and consumes exactly once', () => {
    const store = createMaterialKitHandoffStore();
    store.write(handoff);

    const first = store.consumeMaterialKitHandoff(7);
    expect(first).toEqual(handoff);
    expect(Object.keys(first ?? {}).sort()).toEqual(['applicationId', 'jdText', 'resumeId']);
    expect(first).not.toBe(handoff);
    expect(Object.isFrozen(first)).toBe(true);
    expect(first).not.toHaveProperty('resumeEvidenceProof');
    expect(store.consumeMaterialKitHandoff(7)).toBeNull();
  });

  it('does not consume a handoff for another application', () => {
    const store = createMaterialKitHandoffStore();
    store.write(handoff);

    expect(store.consumeMaterialKitHandoff(8)).toBeNull();
    expect(store.consumeMaterialKitHandoff(7)).toEqual(handoff);
  });

  it('replaces pending state without exposing a mutable original', () => {
    const store = createMaterialKitHandoffStore();
    store.write(handoff);
    store.write({ ...handoff, applicationId: 8, jdText: 'Other JD' });

    expect(store.consumeMaterialKitHandoff(7)).toBeNull();
    expect(store.consumeMaterialKitHandoff(8)?.jdText).toBe('Other JD');
  });
});
