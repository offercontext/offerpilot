export const PILOT_MASCOT_VISIBILITY_KEY = 'offerpilot:pilot-mascot-visible';

export function readPilotMascotVisible(storage?: Pick<Storage, 'getItem'>): boolean {
  try {
    const target = storage ?? window.localStorage;
    return target.getItem(PILOT_MASCOT_VISIBILITY_KEY) !== 'false';
  } catch {
    return true;
  }
}

export function writePilotMascotVisible(
  visible: boolean,
  storage?: Pick<Storage, 'setItem'>,
): void {
  try {
    const target = storage ?? window.localStorage;
    target.setItem(PILOT_MASCOT_VISIBILITY_KEY, String(visible));
  } catch {
    // A blocked storage backend must not affect Pilot availability.
  }
}
