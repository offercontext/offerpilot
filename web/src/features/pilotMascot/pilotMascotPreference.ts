export const PILOT_MASCOT_VISIBILITY_KEY = 'offerpilot:pilot-mascot-visible';
export const PILOT_MASCOT_ZOOM_KEY = 'offerpilot:pilot-mascot-zoom';
export const PILOT_MASCOT_MIN_ZOOM = 0.8;
export const PILOT_MASCOT_MAX_ZOOM = 1.3;
export const PILOT_MASCOT_POSITION_KEY = 'offerpilot:pilot-mascot-position';

export type PilotMascotPlacement = 'normal' | 'interview_studio';
export interface PilotMascotPosition { xRatio: number; yRatio: number }
export interface PilotMascotPositions { version: 1; normal: PilotMascotPosition; interview_studio: PilotMascotPosition }

export const DEFAULT_PILOT_MASCOT_POSITIONS: PilotMascotPositions = {
  version: 1,
  normal: { xRatio: 0.92, yRatio: 0.82 },
  interview_studio: { xRatio: 0.88, yRatio: 0.68 },
};

function normalizeRatio(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(0.98, Math.max(0.02, value));
}

function normalizePosition(value: unknown, fallback: PilotMascotPosition): PilotMascotPosition {
  if (!value || typeof value !== 'object') return fallback;
  const candidate = value as { xRatio?: unknown; yRatio?: unknown };
  if (typeof candidate.xRatio !== 'number' || typeof candidate.yRatio !== 'number' || !Number.isFinite(candidate.xRatio) || !Number.isFinite(candidate.yRatio)) return fallback;
  return { xRatio: normalizeRatio(candidate.xRatio), yRatio: normalizeRatio(candidate.yRatio) };
}

export function readPilotMascotPositions(storage?: Pick<Storage, 'getItem'>): PilotMascotPositions {
  try {
    const raw = (storage ?? window.localStorage).getItem(PILOT_MASCOT_POSITION_KEY);
    if (!raw) return DEFAULT_PILOT_MASCOT_POSITIONS;
    const parsed = JSON.parse(raw) as { version?: unknown; normal?: unknown; interview_studio?: unknown };
    if (parsed.version !== 1) return DEFAULT_PILOT_MASCOT_POSITIONS;
    return {
      version: 1,
      normal: normalizePosition(parsed.normal, DEFAULT_PILOT_MASCOT_POSITIONS.normal),
      interview_studio: normalizePosition(parsed.interview_studio, DEFAULT_PILOT_MASCOT_POSITIONS.interview_studio),
    };
  } catch {
    return DEFAULT_PILOT_MASCOT_POSITIONS;
  }
}

export function writePilotMascotPosition(
  placement: PilotMascotPlacement,
  position: PilotMascotPosition,
  storage?: Pick<Storage, 'getItem' | 'setItem'>,
): void {
  if (!Number.isFinite(position.xRatio) || !Number.isFinite(position.yRatio)) return;
  try {
    const current = readPilotMascotPositions(storage);
    const next = {
      ...current,
      [placement]: normalizePosition(position, current[placement]),
    } as PilotMascotPositions;
    (storage ?? window.localStorage).setItem(PILOT_MASCOT_POSITION_KEY, JSON.stringify(next));
  } catch {
    // Position persistence is an enhancement and must not block the Studio.
  }
}

export function resetPilotMascotPosition(
  placement: PilotMascotPlacement,
  storage?: Pick<Storage, 'getItem' | 'setItem'>,
): void {
  writePilotMascotPosition(placement, DEFAULT_PILOT_MASCOT_POSITIONS[placement], storage);
}

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
