"""Verify One handoff against a real exact engine snapshot, in isolated storage only.

This verifies HTTP/persistence, not an editor browser round trip. No engine writes.
"""
import argparse
import json
from pathlib import Path
import httpx


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--one', required=True)
    p.add_argument('--engine', required=True)
    p.add_argument('--project', required=True)
    p.add_argument('--version', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    with httpx.Client(base_url=args.one, trust_env=False, timeout=60) as one, httpx.Client(base_url=args.engine, trust_env=False, timeout=60) as engine:
        snapshot = engine.get(f'/api/provider/v1/models/{args.project}/versions/{args.version}/snapshot')
        snapshot.raise_for_status()
        pin = snapshot.json()
        before = one.get('/api/v1/applications').json()
        start = one.post('/api/v1/modeling/handoffs', json={'name': 'Professional modeling HTTP acceptance'})
        assert start.status_code == 201, start.text
        session = start.json()
        path = f"/api/v1/modeling/handoffs/{session['handoff_id']}"
        credentials = {k: session[k] for k in ('state', 'confirmation_token')}
        candidate = {**credentials, 'project_id': args.project, 'saved_version': args.version, 'upstream_graph_hash': pin['graph_hash']}
        assert one.post(path + '/preview', json={**candidate, 'state': 'x' * 43}).status_code == 403
        assert one.post(path + '/preview', json={**candidate, 'upstream_graph_hash': '0' * 64}).status_code == 409
        assert one.post(path + '/confirm', json=candidate).status_code == 409
        preview = one.post(path + '/preview', json=candidate)
        assert preview.status_code == 200, preview.text
        assert one.get('/api/v1/applications').json() == before
        confirmed = one.post(path + '/confirm', json=candidate)
        assert confirmed.status_code == 200, confirmed.text
        result = confirmed.json()
        repeated = one.post(path + '/confirm', json=candidate)
        assert repeated.json() == result
        assert len(one.get('/api/v1/applications').json()) == len(before) + 1
        models = one.get(f"/api/v1/applications/{result['application_id']}/system-models").json()
        assert len(models) == 1 and models[0]['upstream_version'] == args.version
        assert models[0]['graph_sha256'] == preview.json()['hydrated_graph_sha256']
        source = one.get(f"/api/v1/applications/{result['application_id']}/model-sources").json()
        assert len(source) == 1 and source[0]['import_receipt']['provider_snapshot']['graph_hash'] == pin['graph_hash']
        cancel_start = one.post('/api/v1/modeling/handoffs', json={'name': 'Cancelled modeling acceptance'}).json()
        cancel_path = f"/api/v1/modeling/handoffs/{cancel_start['handoff_id']}"
        cancel_credentials = {k: cancel_start[k] for k in ('state', 'confirmation_token')}
        assert one.post(cancel_path + '/cancel', json=cancel_credentials).status_code == 200
        assert one.post(cancel_path + '/preview', json={**candidate, **cancel_credentials}).status_code == 410
        assert len(one.get('/api/v1/applications').json()) == len(before) + 1
        evidence = {'verification': 'real-http-no-editor-browser', 'result': result, 'preview': preview.json(),
                    'model': models[0], 'source': source[0], 'one': args.one, 'engine': args.engine,
                    'checks': ['state-refusal', 'hash-refusal', 'preview-before-confirm', 'preview-no-project-write',
                               'exact-pin', 'confirm-idempotent', 'persisted-source', 'cancel-no-project-write']}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': 'passed', 'checks': len(evidence['checks']), 'result': result}))


if __name__ == '__main__':
    main()
