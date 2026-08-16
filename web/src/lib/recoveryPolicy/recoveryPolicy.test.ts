import { describe, expect, it } from 'vitest';
import {
  RECOVERY_POLICIES,
  UNKNOWN_CODE_POLICY,
} from './generatedRecoveryPolicy';
import { resolveErrorRecovery } from './recoveryPolicy';

function httpError(status: number, errorCode?: string) {
  const response: { status: number; data?: { error_code?: string } } = { status };
  if (errorCode !== undefined) response.data = { error_code: errorCode };
  // axios-shaped errors carry the response object.
  return Object.assign(new Error('request failed'), { response });
}

describe('recoveryPolicy resolver (contract-driven, no status guessing)', () => {
  it('resolves every contract error code to its contract disposition', () => {
    const codes = Object.keys(RECOVERY_POLICIES);
    expect(codes.length).toBeGreaterThan(0);
    for (const code of codes) {
      const entry = RECOVERY_POLICIES[code as keyof typeof RECOVERY_POLICIES];
      const decision = resolveErrorRecovery(httpError(entry.http_status, code));
      expect(decision.errorCode, code).toBe(code);
      expect(decision.disposition, code).toBe(entry.disposition);
      expect(decision.preserveIdempotencyKey, code).toBe(entry.preserve_idempotency_key);
      expect(decision.providerRetryAllowed, code).toBe(entry.provider_retry_allowed);
      expect(decision.terminal, code).toBe(entry.disposition === 'terminal_no_retry');
    }
  });

  it('treats provider_error as retry_same_key instead of falling through to a status guess', () => {
    const decision = resolveErrorRecovery(httpError(502, 'mock_interview_provider_error'));
    expect(decision.disposition).toBe('retry_same_key');
    expect(decision.preserveIdempotencyKey).toBe(true);
    expect(decision.terminal).toBe(false);
  });

  it('treats idempotency conflicts as restart_new_attempt, never retry-same-key', () => {
    for (const code of ['mock_interview_idempotency_conflict', 'mock_interview_turn_idempotency_conflict']) {
      const decision = resolveErrorRecovery(httpError(409, code));
      expect(decision.disposition, code).toBe('restart_new_attempt');
      expect(decision.preserveIdempotencyKey, code).toBe(false);
    }
  });

  it('treats unverifiable feedback/question output as terminal with no provider retry', () => {
    const decision = resolveErrorRecovery(httpError(502, 'mock_interview_unverifiable'));
    expect(decision.disposition).toBe('terminal_no_retry');
    expect(decision.providerRetryAllowed).toBe(false);
    expect(decision.terminal).toBe(true);
  });

  it('prefers the error code over the HTTP status when both are present', () => {
    const decision = resolveErrorRecovery(httpError(409, 'mock_interview_provider_error'));
    expect(decision.disposition).toBe('retry_same_key');
  });

  it('fails closed on unknown error codes from the server', () => {
    const decision = resolveErrorRecovery(httpError(500, 'brand_new_error_code'));
    expect(decision.disposition).toBe(UNKNOWN_CODE_POLICY.disposition);
    expect(decision.providerRetryAllowed).toBe(false);
    expect(decision.preserveIdempotencyKey).toBe(false);
    expect(decision.terminal).toBe(true);
  });

  it('fails closed when the server responds without an error code', () => {
    const decision = resolveErrorRecovery(httpError(502));
    expect(decision.disposition).toBe('terminal_no_retry');
    expect(decision.providerRetryAllowed).toBe(false);
  });

  it('keeps frozen keys for transport failures with no server response', () => {
    const decision = resolveErrorRecovery(new Error('network unreachable'));
    expect(decision.disposition).toBe('retry_same_key');
    expect(decision.preserveIdempotencyKey).toBe(true);
    expect(decision.terminal).toBe(false);
  });

  it('maps dispositions to recovery actions the studio can render', () => {
    expect(resolveErrorRecovery(httpError(409, 'mock_interview_source_conflict')).disposition).toBe('reload_source');
    expect(resolveErrorRecovery(httpError(422, 'mock_interview_answer_required')).disposition).toBe('edit_input');
    expect(resolveErrorRecovery(httpError(409, 'mock_interview_attempt_confirmed')).disposition).toBe('terminal_no_retry');
  });
});
