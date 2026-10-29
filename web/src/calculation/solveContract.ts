import type { CalculationMethodRef, SolveAndFreezeRequest } from '../api/types';
import type { CalculationTask } from '../components/CalculationMethodDialog';

/** localStorage bucket that counts failed-solve retries for one idempotency base key. */
export const retryStorageKey = (base: string) => `nebula-one:solve-retry:${base}`;

/** Full identities participate in the digest; UUID/hash concatenation exceeds the API's
 * 128-character key limit, especially once a method or retry suffix is added. */
export async function solveIdempotencyKey(task: CalculationTask, revisionId: string, contentHash: string,
  method?: CalculationMethodRef): Promise<string> {
  const identity = JSON.stringify([task, revisionId, contentHash,
    method ? [method.method_id, method.version, method.content_sha256] : null]);
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(identity));
  const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  return `calc-v3-${task}:${hash}`;
}

/** A retried solve must not replay as a conflicting identical request, so a positive retry count
 * moves to a derived key; the first attempt keeps the base key unchanged. */
export const withRetrySuffix = (base: string, retries: number) =>
  Number.isSafeInteger(retries) && retries > 0 ? `${base}:retry-${retries}` : base;

export interface SolvePayloadInput {
  demand: SolveAndFreezeRequest['demand'];
  idempotencyKey: string;
  retries?: number;
  task?: CalculationTask;
  backgroundProcessPins?: SolveAndFreezeRequest['background_process_pins'];
  mappedBackgroundProcessPins?: SolveAndFreezeRequest['mapped_background_process_pins'];
  projectBackgroundPins?: SolveAndFreezeRequest['project_background_pins'];
  calculationMethodRef?: CalculationMethodRef;
  calculationPurpose?: string;
  nativeBackgroundInventory?: boolean;
  lciaMethods?: string[];
}

/** The one place a solve request is assembled, so every calculation entry point (workbench,
 * professional modeling, scenario case) emits the same contract for the same intent. A field is
 * omitted unless the caller supplies it, which keeps an MFA-only quick start minimal while a
 * full task pins its background bindings, method version and climate basis exactly as before. */
export function buildSolvePayload(input: SolvePayloadInput): SolveAndFreezeRequest {
  const payload: SolveAndFreezeRequest = { demand: input.demand };
  if (input.backgroundProcessPins !== undefined) payload.background_process_pins = input.backgroundProcessPins;
  if (input.mappedBackgroundProcessPins !== undefined) payload.mapped_background_process_pins = input.mappedBackgroundProcessPins;
  if (input.projectBackgroundPins?.length) payload.project_background_pins = input.projectBackgroundPins;
  payload.idempotency_key = withRetrySuffix(input.idempotencyKey, input.retries ?? 0);
  // A bare CBAM trial with neither a purpose nor a cited method derives its own boundary and so
  // names no analysis task; every other task keys its run by the task it is actually computing.
  if (input.task && !(input.task === 'cbam' && !input.calculationPurpose && !input.calculationMethodRef)) {
    payload.analysis_task = input.task;
  }
  if (input.calculationMethodRef) payload.calculation_method_ref = input.calculationMethodRef;
  if (input.calculationPurpose) payload.calculation_purpose = input.calculationPurpose;
  if (input.nativeBackgroundInventory) payload.native_background_inventory = true;
  else if (input.task === 'pcf' || input.task === 'organization') payload.climate_default = true;
  if (input.lciaMethods?.length) payload.lcia_methods = input.lciaMethods;
  return payload;
}
