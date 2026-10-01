import json
from pathlib import Path

from nebula_one.seeds import prepare_open_supply_flow as importer
from desktop.build_payload import validate_public_payload
import pytest


def test_open_flow_import_uses_exact_ports_from_current_source_independent_of_order(monkeypatch):
    seed = json.loads(importer.SUPPLY_PATH.read_text(encoding='utf-8'))
    seed['graph']['nodes'][0]['outputs'].reverse()
    original = importer.SUPPLY_PATH
    seen = []
    # Reordered upstream ports must resolve by the pinned UUID, not array position.
    class Source:
        def read_text(self, **kwargs):
            return json.dumps(seed)
    monkeypatch.setattr(importer, 'SUPPLY_PATH', Source())
    monkeypatch.setattr(importer, '_ensure_pinned_open_flow', lambda client, pin, port: seen.append(port) or {})
    monkeypatch.setattr(importer, '_ensure_versioned_open_flow', lambda client, pin, port: seen.append(port) or {})
    importer.ensure_open_supply_flow(object())
    assert original.name == 'tiangong-china-grid-2022.v1.json'
    assert [port['flowUuid'] for port in seen] == [pin['flow_uuid'] for pin in importer.open_flow_pins()]


@pytest.mark.parametrize('relative', [
    'backends/api/data/Tiangong/tiangong_processes.zip',
    'backends/api/solver-data/EF3.1/lcia_factors.csv',
    'backends/one/nebula_one/resources/public_supply/china-grid-co2-2023.v1.json',
])
def test_payload_rejects_legacy_assets_even_in_frozen_backend_copy(tmp_path, relative):
    file = tmp_path / relative
    file.parent.mkdir(parents=True)
    file.write_bytes(b'not redistributed')
    with pytest.raises(ValueError, match='Unneeded legacy asset'):
        validate_public_payload(tmp_path)
