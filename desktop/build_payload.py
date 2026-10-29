"""Stage only explicit public assets and frozen backends for the desktop build."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path


def run(command, cwd, *, env=None):
    subprocess.run(command, cwd=cwd, env=env, check=True)


class EditorAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'script' and attrs.get('src'):
            self.urls.append(attrs['src'])
        if tag == 'link' and attrs.get('rel') in {'stylesheet', 'modulepreload'}:
            self.urls.append(attrs['href'])


def validate_editor_assets(editor):
    assets = EditorAssets()
    assets.feed((editor / 'index.html').read_text(encoding='utf-8'))
    if not assets.urls:
        raise ValueError('Editor build has no script or stylesheet assets')
    for url in assets.urls:
        if not url.startswith('/assets/'):
            raise ValueError(f'Desktop HTTP editor needs root asset URLs: {url}')
        file = (editor / url.lstrip('/')).resolve()
        file.relative_to(editor.resolve())
        if not file.is_file():
            raise FileNotFoundError(file)


def validate_public_payload(target):
    forbidden = {'ILCD_Unit_Groups.xlsx', 'elementary_flows_sample.csv',
                 'intermediate_flows_sample.csv', 'tiangong_processes.zip',
                 'china-grid-co2-2023.v1.json', 'ghg_ef31_v1.json'}
    for file in target.rglob('*'):
        if file.is_file() and (file.name in forbidden or 'solver-data' in file.parts):
            raise ValueError(f'Unneeded legacy asset in desktop payload: {file.relative_to(target)}')


def validate_ef31_characterization(target):
    """Verify the public EF3.1 characterization runtime is present and loadable."""
    char_dir = target / 'backends/nebula-lca-api/_internal/data/ef31-characterization'
    if not char_dir.is_dir():
        raise FileNotFoundError(f'EF3.1 characterization runtime missing: {char_dir}')
    required = ('flow_index.csv', 'indicator_index.csv', 'lcia_factors.csv')
    for name in required:
        f = char_dir / name
        if not f.is_file():
            raise FileNotFoundError(f'EF3.1 characterization asset missing: {f}')
        if f.stat().st_size == 0:
            raise ValueError(f'EF3.1 characterization asset empty: {f}')
    # indicator_index must carry ecoinvent_category for canonical key resolution
    header = (char_dir / 'indicator_index.csv').read_text(encoding='utf-8-sig').splitlines()[0]
    if 'ecoinvent_category' not in header:
        raise ValueError('EF3.1 indicator_index.csv lacks ecoinvent_category column; '
                         'characterization canonical keys will not resolve')


# Commercially derived characterization tables the user holds locally under a licence that does
# not permit redistribution.  They are identified by content, not by path, so renaming a copy
# cannot smuggle them into a public build.
FORBIDDEN_CHARACTERIZATION_SHA256 = {
    '21f8ea69c6a73b1fbb2a30538911113e9795fbdc3713e61f318624bf9792b0ce':
        'ecoinvent-derived EF3.1 flow_index.csv',
    'ac319af1b1eca835df6e80783af486875d04543dbc7a326789fa36a72f0193d3':
        'ecoinvent-derived EF3.1 lcia_factors.csv',
    # runtime/ef31/lcia-official-3.11-all-methods: the ecoinvent LCIA-implementation method
    # package (9795 flows, 633 indicators, 481813 factors; CML/ReCiPe/TRACI/"no LT" variants).
    # It is the FIRST characterization source the engine merges in desktop mode, so a payload
    # carrying it would silently outrank the license-clean public trio.
    'd8b03f615ea85b4208d02f83ebda8ee1e3f275c6d32c5aca5448ab767c37d843':
        'ecoinvent-derived lcia-official-3.11-all-methods flow_index.csv',
    '0c270c402e1372da66353a5da5a8f3a4e38a83a0b2d18b52513f0997f2789aeb':
        'ecoinvent-derived lcia-official-3.11-all-methods lcia_factors.csv',
    'da5f6caf96d07173b76fb2131c1e0fea64fe789d11a8c3883373f76ae7cac256':
        'ecoinvent-derived lcia-official-3.11-all-methods indicator_index.csv',
}

# Every directory the engine's characterization resolver (_embedded_ef31_candidates) can reach
# inside the bundle. Scanning only data/ left runtime/ and solver-data/ unguarded.
_CHARACTERIZATION_SCAN_ROOTS = ('data', 'runtime', 'solver-data')


def validate_no_commercial_characterization(target):
    """Refuse to stage a public payload that still carries ecoinvent-derived factor tables."""
    internal = target / 'backends/nebula-lca-api/_internal'
    api_data = internal / 'data'
    if not api_data.is_dir():
        raise FileNotFoundError(f'LCA API data payload missing: {api_data}')
    legacy = api_data / 'EF3.1'
    if legacy.is_dir():
        # data/EF3.1 keeps only the indicator/unit metadata table consumed by provider_ef31;
        # characterization is served solely by the license-clean data/ef31-characterization trio.
        for name in ('flow_index.csv', 'lcia_factors.csv'):
            if (legacy / name).is_file():
                raise ValueError(
                    f'ecoinvent-derived characterization asset in public payload: '
                    f'{legacy.relative_to(target) / name}')
    seeded = internal / 'runtime' / 'ef31'
    if seeded.is_dir():
        # desktop_entry._seed_runtime_if_needed copies this tree into the user's data dir on first
        # boot, where it wins characterization order over NEBULA_LCA_EF31_DIR.
        raise ValueError(f'bundled EF3.1 runtime in public payload: {seeded.relative_to(target)}')
    for root_name in _CHARACTERIZATION_SCAN_ROOTS:
        root = internal / root_name
        if not root.is_dir():
            continue
        for file in root.rglob('*'):
            if not file.is_file() or file.suffix.lower() not in {'.csv', '.json'}:
                continue
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            label = FORBIDDEN_CHARACTERIZATION_SHA256.get(digest)
            if label:
                raise ValueError(f'{label} in public payload: {file.relative_to(target)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lca-root', type=Path, required=True)
    parser.add_argument('--skip-web-build', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lca = args.lca_root.resolve()
    target = root / 'desktop/resources'
    # Old prototype builds used these root slots. They are generated staging output,
    # never user data, and must not survive alongside the current explicit backends.
    for name in ('one-api', 'lca-api', 'solver', 'solver-data'):
        obsolete = target / name
        obsolete.resolve().relative_to(target.resolve())
        if obsolete.exists():
            shutil.rmtree(obsolete)
    if not args.skip_web_build:
        run(['npm.cmd', 'run', 'build'], root / 'web')
        run(['npm.cmd', 'run', 'build'], lca / 'nebula-lca-web',
            env={**os.environ, 'VITE_WEB_ASSET_BASE': '/'})
    validate_editor_assets(lca / 'nebula-lca-web/dist')
    copies = [
        (root / 'build/desktop-backends/nebula-one-api', target / 'backends/nebula-one-api'),
        (lca / 'build/desktop-backends/nebula-lca-api', target / 'backends/nebula-lca-api'),
        (root / 'web/dist', target / 'web'),
        (lca / 'nebula-lca-web/dist', target / 'editor'),
        (root / 'cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel', target / 'cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel'),
        (root / 'cases/project-templates/steel-bf-bof-inventory', target / 'cases/project-templates/steel-bf-bof-inventory'),
        (root / 'src/nebula_one/resources', target / 'src/nebula_one/resources'),
    ]
    for source, destination in copies:
        if not source.is_dir():
            raise FileNotFoundError(source)
        # Remove stale staged output, never runtime/user data.
        destination.resolve().relative_to(target.resolve())
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('china-grid-co2-2023.v1.json'))
    (target / 'config').mkdir(parents=True, exist_ok=True)
    from open_flow_snapshot import compose_flow_snapshots, compose_elementary_catalog
    flows = compose_flow_snapshots([
        lca / 'nebula-lca-api/data/provider_profiles/steel_tiangong_open_flows.v2.json',
        root / 'src/nebula_one/resources/desktop_extra_tiangong_flows.v1.json',
    ])
    (target / 'config/desktop_tiangong_open_flows.v1.json').write_text(
        json.dumps(flows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    profiles = lca / 'nebula-lca-api/data/provider_profiles'
    extra = root / 'src/nebula_one/resources'
    catalog, profile = compose_elementary_catalog(profiles / 'steel_elementary_catalog.v1.csv',
        extra / 'desktop_extra_elementary_catalog.v1.csv', profiles / 'steel_elementary_catalog.v1.provenance.json',
        extra / 'desktop_extra_elementary_catalog.v1.provenance.json')
    (target / 'config/desktop_elementary_catalog.v1.csv').write_bytes(catalog)
    (target / 'config/desktop_elementary_catalog.v1.provenance.json').write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    seed_config = json.loads((root / 'deploy/seeds/steel-demo.json').read_text(encoding='utf-8'))
    seed_config['steps'] = [step for step in seed_config['steps']
                            if step.get('seed_id') != 'china-national-grid-co2-2023']
    (target / 'config/steel-demo.json').write_text(json.dumps(seed_config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(root / 'deploy/public-catalog.v1.json', target / 'config/public-catalog.v1.json')
    (target / 'licenses').mkdir(exist_ok=True)
    shutil.copy2(root / 'LICENSE', target / 'licenses/nebula-one.txt')
    shutil.copy2(lca / 'LICENSE', target / 'licenses/nebula-lca.txt')
    tiangong = lca / 'nebula-lca-api/data/Tiangong'
    shutil.copy2(tiangong / 'LICENSE.TianGong', target / 'licenses/tiangong-MIT.txt')
    shutil.copy2(tiangong / 'NOTICE.md', target / 'licenses/tiangong-NOTICE.md')
    shutil.copy2(root / 'docs/DATA_PROVENANCE.md', target / 'licenses/DATA_PROVENANCE.md')
    shutil.copy2(root / 'docs/RETAINED_SOURCE_DECLARATIONS.md', target / 'licenses/RETAINED_SOURCE_DECLARATIONS.md')
    shutil.copy2(root / 'docs/DESKTOP_DATA_INVENTORY.md', target / 'licenses/DESKTOP_DATA_INVENTORY.md')
    # JRC ILCD EF3.1 characterization attribution (public data, free redistribution with credit)
    ef31_prov = lca / 'nebula-lca-solver/data/EF3.1-public/provenance.json'
    if ef31_prov.is_file():
        shutil.copy2(ef31_prov, target / 'licenses/ef31-characterization-provenance.json')
    mapping = lca / 'nebula-lca-api/data/flow_mappings/nebula-flow-mapping-v1'
    for name in ('LICENSE', 'NOTICE.md'):
        shutil.copy2(mapping / name, target / 'licenses' / f'flow-mapping-{name}')
    run([str(root / 'build/desktop-venv/Scripts/python.exe'), str(root / 'desktop/dependency_notices.py'),
         str(target / 'licenses/python')], root)
    run([str(root / 'build/desktop-venv/Scripts/python.exe'), str(root / 'desktop/javascript_notices.py'),
         '--one-web', str(root / 'web'), '--lca-web', str(lca / 'nebula-lca-web'),
         '--output', str(target / 'licenses/javascript')], root)
    validate_public_payload(target)
    validate_ef31_characterization(target)
    validate_no_commercial_characterization(target)
    records = []
    for file in sorted(target.rglob('*')):
        if file.is_file() and file.name != 'payload-manifest.json':
            records.append({'path': file.relative_to(target).as_posix(), 'size': file.stat().st_size,
                            'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    manifest = {'schema_version': 'nebula_one.desktop_payload.v1',
                'one_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                'lca_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=lca, text=True).strip(),
                'files': records}
    (target / 'payload-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'Staged {len(records)} files at {target}')


if __name__ == '__main__':
    main()
