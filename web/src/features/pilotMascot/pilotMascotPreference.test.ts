// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  PILOT_MASCOT_VISIBILITY_KEY,
  readPilotMascotVisible,
  writePilotMascotVisible,
} from './pilotMascotPreference';

describe('pilot mascot preference', () => {
  beforeEach(() => localStorage.clear());

  it('defaults to visible and persists explicit choices', () => {
    expect(readPilotMascotVisible()).toBe(true);
    writePilotMascotVisible(false);
    expect(localStorage.getItem(PILOT_MASCOT_VISIBILITY_KEY)).toBe('false');
    expect(readPilotMascotVisible()).toBe(false);
    writePilotMascotVisible(true);
    expect(readPilotMascotVisible()).toBe(true);
  });

  it('fails open when storage is unavailable', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readPilotMascotVisible()).toBe(true);
    getItem.mockRestore();
  });
});
