import { describe, expect, it } from 'vitest';
import { derivePilotMascotActivity } from './pilotMascotActivity';

describe('derivePilotMascotActivity', () => {
  it.each([
    [{ loading: false, confirmationPhase: 'idle', hasError: false, degraded: false }, 'idle'],
    [{ loading: true, confirmationPhase: 'idle', hasError: false, degraded: false }, 'thinking'],
    [{ loading: false, confirmationPhase: 'saving', hasError: false, degraded: false }, 'thinking'],
    [{ loading: false, confirmationPhase: 'success', hasError: false, degraded: false }, 'success'],
    [{ loading: false, confirmationPhase: 'idle', hasError: true, degraded: false }, 'error'],
    [{ loading: false, confirmationPhase: 'idle', hasError: false, degraded: true }, 'error'],
  ] as const)('maps real Pilot facts to %s', (facts, expected) => {
    expect(derivePilotMascotActivity(facts)).toBe(expected);
  });
});
