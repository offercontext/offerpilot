export const PILOT_MASCOT_VISIBILITY_KEY = 'offerpilot:pilot-mascot-visible';
export const PILOT_MASCOT_ZOOM_KEY = 'offerpilot:pilot-mascot-zoom';
export const PILOT_MASCOT_MIN_ZOOM = 0.8;
export const PILOT_MASCOT_MAX_ZOOM = 1.3;

export function normalizePilotMascotZoom(value: number): number {
  if (!Number.isFinite(value)) return 1;
  const stepped = Math.round(value * 10) / 10;
  return Math.min(PILOT_MASCOT_MAX_ZOOM, Math.max(PILOT_MASCOT_MIN_ZOOM, stepped));
}

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

export function readPilotMascotZoom(storage?: Pick<Storage, 'getItem'>): number {
  try {
    const target = storage ?? window.localStorage;
    const stored = target.getItem(PILOT_MASCOT_ZOOM_KEY);
    if (stored === null || stored.trim() === '') return 1;
    const parsed = Number(stored);
    return Number.isFinite(parsed) ? normalizePilotMascotZoom(parsed) : 1;
  } catch {
    return 1;
  }
}

export function writePilotMascotZoom(
  zoom: number,
  storage?: Pick<Storage, 'setItem'>,
): void {
  if (!Number.isFinite(zoom)) return;
  try {
    const target = storage ?? window.localStorage;
    target.setItem(PILOT_MASCOT_ZOOM_KEY, String(normalizePilotMascotZoom(zoom)));
  } catch {
    // A blocked storage backend must not affect Pilot availability.
  }
}
