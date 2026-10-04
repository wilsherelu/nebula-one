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
                 'china-grid-co2-2023.v1.json'}
    for file in target.rglob('*'):
        if file.is_file() and (file.name in forbidden or 'solver-data' in file.parts):
            raise ValueError(f'Unneeded legacy asset in desktop payload: {file.relative_to(target)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lca-root', type=Path, required=True)
    parser.add_argument('--skip-web-build', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lca = args.lca_root.resolve()
    target = root / 'desktop/resources'
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
    mapping = lca / 'nebula-lca-api/data/flow_mappings/nebula-flow-mapping-v1'
    for name in ('LICENSE', 'NOTICE.md'):
        shutil.copy2(mapping / name, target / 'licenses' / f'flow-mapping-{name}')
    run([str(root / 'build/desktop-venv/Scripts/python.exe'), str(root / 'desktop/dependency_notices.py'),
         str(target / 'licenses/python')], root)
    validate_public_payload(target)
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
