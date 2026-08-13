import type { PilotMascotActivity } from './PilotMascot';

interface PilotActivityFacts {
  loading: boolean;
  confirmationPhase: 'idle' | 'saving' | 'success' | 'error';
  hasError: boolean;
  degraded: boolean;
}

export function derivePilotMascotActivity({
  loading,
  confirmationPhase,
  hasError,
  degraded,
}: PilotActivityFacts): PilotMascotActivity {
  if (loading || confirmationPhase === 'saving') return 'thinking';
  if (hasError || degraded || confirmationPhase === 'error') return 'error';
  if (confirmationPhase === 'success') return 'success';
  return 'idle';
}
