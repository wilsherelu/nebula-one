"""Read-only verification of an explicit quantity definition over a real frozen CBAM solve.

The input evidence is {path, request, result} captured from the live cbam-trial API.
This test replays the formal service preparation and analyzer against the same
database in SQLite read-only mode. It does not register a new business method.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import sqlite3
import subprocess

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from nebula_one.analysis.accounting_quantity_basis import climate_intensity_definition
from nebula_one.analysis.cbam_trial import build_cbam_trial
from nebula_one.analysis.cbam_trial_v2 import build_cbam_trial_v2
from nebula_one.errors import DomainError
from nebula_one.runtime_schemas import CbamTrialCreate
from nebula_one.services.cbam_trial import CbamTrialService


def run(database: Path, evidence: Path, output: Path) -> dict:
    original = json.loads(evidence.read_text(encoding='utf-8'))
    snapshot_id = original['path'].split('/solved-system-snapshots/', 1)[1].split('/')[0]
    engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(
        database.resolve().as_uri() + '?mode=ro', uri=True))
    try:
        with Session(engine) as db:
            prepared = CbamTrialService(None)._prepare(db, snapshot_id, CbamTrialCreate.model_validate(original['request']))
    finally:
        engine.dispose()
    if prepared['precursor_specs']:
        raise RuntimeError('this direct-component acceptance requires a snapshot without external precursor results')

    def calculate(definition=None):
        common = deepcopy(prepared['common'])
        if definition is not None:
            common['manifest']['accounting_quantity_basis'] = definition
        if prepared['schema_version'].endswith('.v1'):
            return build_cbam_trial(**common)
        return build_cbam_trial_v2(**common, **prepared['v2'], precursor_results=[])

    legacy = calculate()
    assert legacy == original['result'], 'legacy result or content hash changed'
    explicit = calculate(climate_intensity_definition())
    receipt = explicit['direct_quantity_basis_receipt']
    assert receipt['missing'] == []
    assert receipt['numerator'] == legacy['attributed_emissions']['direct']['value']
    assert receipt['denominator'] == legacy['activity_level']['value']
    without_receipt = {k: v for k, v in explicit.items() if k not in {'direct_quantity_basis_receipt', 'content_sha256'}}
    assert without_receipt == {k: v for k, v in legacy.items() if k != 'content_sha256'}
    bad = climate_intensity_definition()
    bad['denominator']['target_unit'] = 'kg'
    try:
        calculate(bad)
    except DomainError as error:
        assert error.code == 'ACCOUNTING_QUANTITY_RESULT_CONTRACT_MISMATCH'
    else:
        raise AssertionError('wrong denominator unit accepted')
    report = dict(passed=5, failed=0, evidence_level='real_frozen_snapshot_readonly_service_seam',
                  snapshot_id=snapshot_id, legacy_content_sha256=legacy['content_sha256'],
                  explicit_content_sha256=explicit['content_sha256'], receipt=receipt,
                  checks=['legacy_full_json_and_hash_unchanged', 'numerator_matches_ledger',
                          'denominator_matches_reference_output', 'explicit_definition_other_fields_equal',
                          'wrong_denominator_unit_refused'])
    root = Path(__file__).resolve().parents[1]
    report['one_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    report['source_sha256'] = {name: hashlib.sha256((root / 'src/nebula_one/analysis' / name).read_bytes()).hexdigest()
                               for name in ('accounting_quantity_basis.py', 'cbam_trial.py', 'cbam_trial_v2.py')}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.database, args.evidence, args.output), ensure_ascii=True))
