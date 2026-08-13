// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  PILOT_MASCOT_ZOOM_KEY,
  PILOT_MASCOT_VISIBILITY_KEY,
  readPilotMascotZoom,
  readPilotMascotVisible,
  writePilotMascotZoom,
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

  it('defaults zoom to 100% and persists clamped ten-percent steps', () => {
    expect(readPilotMascotZoom()).toBe(1);
    writePilotMascotZoom(1.24);
    expect(localStorage.getItem(PILOT_MASCOT_ZOOM_KEY)).toBe('1.2');
    expect(readPilotMascotZoom()).toBe(1.2);
    writePilotMascotZoom(9);
    expect(readPilotMascotZoom()).toBe(1.3);
    writePilotMascotZoom(-9);
    expect(readPilotMascotZoom()).toBe(0.8);
  });

  it('rejects malformed and non-finite zoom values without breaking Pilot', () => {
    localStorage.setItem(PILOT_MASCOT_ZOOM_KEY, 'not-a-number');
    expect(readPilotMascotZoom()).toBe(1);
    localStorage.setItem(PILOT_MASCOT_ZOOM_KEY, 'Infinity');
    expect(readPilotMascotZoom()).toBe(1);
    expect(() => writePilotMascotZoom(Number.NaN)).not.toThrow();
    expect(readPilotMascotZoom()).toBe(1);

    const blocked = {
      getItem: vi.fn(() => { throw new Error('blocked'); }),
      setItem: vi.fn(() => { throw new Error('blocked'); }),
    };
    expect(readPilotMascotZoom(blocked)).toBe(1);
    expect(() => writePilotMascotZoom(1.2, blocked)).not.toThrow();
  });
});
