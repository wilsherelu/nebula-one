import json
from pathlib import Path
import pytest
from desktop.open_flow_snapshot import compose_flow_snapshots, compose_elementary_catalog, digest

EXTRA = Path('src/nebula_one/resources/desktop_extra_tiangong_flows.v1.json')


def test_methane_is_an_exact_open_flow_with_original_payload_and_no_factors():
    source = json.loads(EXTRA.read_text(encoding='utf-8'))
    result = compose_flow_snapshots([EXTRA])
    assert result['records'] == source['records']
    assert result['filters']['exact_refs'] == ['08a91e70-3ddc-11dd-9610-0050c2490048@03.00.004']
    assert result['records'][0]['content_hash'] == '23aa3f99f3bb7ef87eb2e421adb9006f12a63c4c5c8dd502f89862bec733fc17'
    assert 'cf_value' not in json.dumps(result)


def test_duplicate_input_deduplicates_without_rewriting_the_record():
    result = compose_flow_snapshots([EXTRA, EXTRA])
    assert len(result['records']) == 1


def test_drift_and_non_open_data_are_refused(tmp_path):
    source = json.loads(EXTRA.read_text(encoding='utf-8'))
    source['state_scope'] = 'all'
    target = tmp_path / 'wrong.json'
    target.write_text(json.dumps(source), encoding='utf-8')
    with pytest.raises(ValueError):
        compose_flow_snapshots([target])
    source['state_scope'] = 'open'
    source['records'][0]['content_hash'] = '0' * 64
    target.write_text(json.dumps(source), encoding='utf-8')
    with pytest.raises(ValueError):
        compose_flow_snapshots([target])
    source['snapshot_hash'] = digest({key: source[key] for key in (
        'schema_version', 'source_namespace', 'dataset_kind', 'state_scope', 'filters', 'declared_total', 'records')})
    target.write_text(json.dumps(source), encoding='utf-8')
    with pytest.raises(ValueError):
        compose_flow_snapshots([EXTRA, target])


def test_compatibility_catalog_keeps_exact_metadata_and_checks_input_hashes(tmp_path):
    import hashlib
    extra = Path('src/nebula_one/resources/desktop_extra_elementary_catalog.v1.csv')
    provenance = extra.with_suffix('.provenance.json')
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'selected_sha256': hashlib.sha256(extra.read_bytes()).hexdigest(),
        'schema_version': 'nebula_lca.selected-elementary-catalog.v1', 'unit_group_names': ['Units of mass']}), encoding='utf-8')
    data, merged = compose_elementary_catalog(extra, extra, profile, provenance)
    assert len(data.decode('utf-8').splitlines()) == 2
    assert merged['flow_uuids'] == ['08a91e70-3ddc-11dd-9610-0050c2490048']
    assert merged['selected_sha256'] == hashlib.sha256(data).hexdigest()
    profile.write_text(json.dumps({'selected_sha256': '0' * 64}), encoding='utf-8')
    with pytest.raises(ValueError):
        compose_elementary_catalog(extra, extra, profile, provenance)
