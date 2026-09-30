from io import BytesIO
import json
from zipfile import ZipFile

import pytest

from nebula_one.hashing import canonical_json_sha256
from nebula_one.seeds.standard_seed_bundle import SeedBuild, resolve_seed_directory
from nebula_one.seeds.steel_flow_versions import steel_flow_version_bundle


def test_catalog_supplement_pins_authored_semantics_without_a_project_or_factors():
    steel=SeedBuild(resolve_seed_directory('iron-steel-bf-bof-crude-steel',None))
    original_pins=steel.pins()
    payload,snapshots=steel_flow_version_bundle(steel)
    with ZipFile(BytesIO(payload)) as archive:
        assert set(archive.namelist())=={'manifest.json','catalog/flows.json','catalog/flow_versions.json'}
        rows=json.loads(archive.read('catalog/flows.json'))
    assert len(snapshots)==len(rows)==16
    assert steel.pins()==original_pins
    semantic_keys=('flow_uuid','source_namespace','source_version','flow_name','flow_name_en','flow_type','default_unit','unit_group','flow_property_uuid','flow_property_version','unit_group_uuid','unit_group_version')
    for snapshot in snapshots:
        assert snapshot['content_hash']==canonical_json_sha256({key:snapshot[key] for key in semantic_keys})
        assert snapshot['flow_property_version']=='03.00.003'
        assert snapshot['unit_group_version']=='03.00.003'
        row=next(r for r in rows if r['flow_uuid']==snapshot['flow_uuid'])
        assert row['source_namespace']==snapshot['source_namespace']
        assert row['source_version']==snapshot['source_version']


def test_same_authored_flow_cannot_claim_two_property_versions():
    steel=SeedBuild(resolve_seed_directory('iron-steel-bf-bof-crude-steel',None))
    steel.validate()
    steel.validate=lambda:None
    flow=steel.graph['nodes'][0]['outputs'][0]['flowUuid']
    port=next(p for n in steel.graph['nodes'] for p in n.get('inputs',[]) if p['flowUuid']==flow)
    port['flowPropertyVersion']='03.00.099'
    with pytest.raises(ValueError,match='disagree'):
        steel_flow_version_bundle(steel)
