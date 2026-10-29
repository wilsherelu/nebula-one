"""The public payload must carry only license-clean characterization assets.

The engine merges EVERY characterization directory it can reach inside the bundle and the first
source wins each (indicator, flow) key, so a commercial table anywhere under ``_internal`` — not
just under ``_internal/data`` — would silently outrank the public trio.
"""
import hashlib
from pathlib import Path

import pytest

from desktop.build_payload import (
    FORBIDDEN_CHARACTERIZATION_SHA256,
    validate_no_commercial_characterization,
)

INTERNAL = Path('backends/nebula-lca-api/_internal')


def _clean_payload(root: Path) -> Path:
    char = root / INTERNAL / 'data' / 'ef31-characterization'
    char.mkdir(parents=True)
    (char / 'flow_index.csv').write_text('flow_index;FlowUUID;FlowName\n0;x;y\n', encoding='utf-8')
    (char / 'indicator_index.csv').write_text(
        'indicator_index;ecoinvent_category\n1;climate change\n', encoding='utf-8')
    (char / 'lcia_factors.csv').write_text('row;column;coefficient\n1;0;1.0\n', encoding='utf-8')
    return root


def test_clean_payload_passes(tmp_path):
    validate_no_commercial_characterization(_clean_payload(tmp_path))


def test_bundled_ef31_runtime_is_refused_wherever_it_sits(tmp_path):
    _clean_payload(tmp_path)
    seeded = tmp_path / INTERNAL / 'runtime' / 'ef31' / 'lcia-official-3.11-all-methods'
    seeded.mkdir(parents=True)
    (seeded / 'flow_index.csv').write_text('flow_index;FlowUUID;FlowName\n', encoding='utf-8')
    with pytest.raises(ValueError, match='bundled EF3.1 runtime'):
        validate_no_commercial_characterization(tmp_path)


@pytest.mark.parametrize('relative', [
    'data/renamed-dir/renamed.csv',
    # Both of these sit outside _internal/data, which was the only root scanned before the
    # resolver's full candidate list was taken into account.
    'runtime/lcia/renamed.csv',
    'solver-data/EF3.1/renamed.csv',
])
def test_forbidden_content_is_caught_by_digest_not_by_path(tmp_path, relative):
    _clean_payload(tmp_path)
    smuggled = tmp_path / INTERNAL / relative
    smuggled.parent.mkdir(parents=True)
    smuggled.write_text('row;column;coefficient\n9;9;9.9\n', encoding='utf-8')
    digest = hashlib.sha256(smuggled.read_bytes()).hexdigest()
    original = dict(FORBIDDEN_CHARACTERIZATION_SHA256)
    FORBIDDEN_CHARACTERIZATION_SHA256.clear()
    FORBIDDEN_CHARACTERIZATION_SHA256[digest] = 'test-only forbidden table'
    try:
        with pytest.raises(ValueError, match='test-only forbidden table'):
            validate_no_commercial_characterization(tmp_path)
    finally:
        FORBIDDEN_CHARACTERIZATION_SHA256.clear()
        FORBIDDEN_CHARACTERIZATION_SHA256.update(original)


def test_ecoinvent_official_runtime_digests_are_registered():
    # Audit record: the ecoinvent 3.11 LCIA-implementation runtime that desktop builds seed into
    # the data dir must be refused by content even if it is renamed or repacked.
    for digest in (
        'd8b03f615ea85b4208d02f83ebda8ee1e3f275c6d32c5aca5448ab767c37d843',
        '0c270c402e1372da66353a5da5a8f3a4e38a83a0b2d18b52513f0997f2789aeb',
        'da5f6caf96d07173b76fb2131c1e0fea64fe789d11a8c3883373f76ae7cac256',
    ):
        assert digest in FORBIDDEN_CHARACTERIZATION_SHA256
