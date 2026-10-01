"""Stage only explicit public assets and frozen backends for the desktop build."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def run(command, cwd):
    subprocess.run(command, cwd=cwd, check=True)


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
        run(['npm.cmd', 'run', 'build'], lca / 'nebula-lca-web')
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
        shutil.copytree(source, destination)
    (target / 'config').mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / 'deploy/seeds/steel-demo.json', target / 'config/steel-demo.json')
    shutil.copy2(root / 'deploy/public-catalog.v1.json', target / 'config/public-catalog.v1.json')
    (target / 'licenses').mkdir(exist_ok=True)
    shutil.copy2(root / 'LICENSE', target / 'licenses/nebula-one.txt')
    shutil.copy2(lca / 'LICENSE', target / 'licenses/nebula-lca.txt')
    shutil.copy2(root / 'docs/DATA_PROVENANCE.md', target / 'licenses/DATA_PROVENANCE.md')
    run([str(root / 'build/desktop-venv/Scripts/python.exe'), str(root / 'desktop/dependency_notices.py'),
         str(target / 'licenses/python')], root)
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
