import { describe, expect, it } from 'vitest';
import { parseModelingReturn } from './ModelingReturnPage';

const storage = JSON.stringify({state: 'state-example', confirmation_token: 'secret-in-original-tab'});
const query = () => new URLSearchParams({handoff_id: '12345678-1234-1234-1234-123456789abc', state: 'state-example', project_id: 'project-1', saved_version: '3', upstream_graph_hash: 'a'.repeat(64)});
describe('modeling return candidates', () => {
  it('uses the original tab confirmation secret, not a callback-provided token', () => {
    const p = query(); p.set('confirmation_token', 'attacker');
    expect(parseModelingReturn(p, storage).candidate?.confirmation_token).toBe('secret-in-original-tab');
  });
  it('rejects missing or mismatched original session', () => {
    expect(() => parseModelingReturn(query(), null)).toThrow();
    const p = query(); p.set('state', 'other');
    expect(() => parseModelingReturn(p, storage)).toThrow();
  });
  it.each(['latest', '', '0', '-1', '1.5', '9007199254740993'])('rejects invalid saved version %s', version => {
    const p = query(); p.set('saved_version', version);
    expect(() => parseModelingReturn(p, storage)).toThrow();
  });
  it('rejects duplicate identity and recognizes cancellation without a version', () => {
    const p = query(); p.append('project_id', 'other');
    expect(() => parseModelingReturn(p, storage)).toThrow();
    const cancelled = query(); cancelled.set('status', 'cancelled'); cancelled.delete('saved_version');
    expect(parseModelingReturn(cancelled, storage).cancelled).toBe(true);
  });
});
