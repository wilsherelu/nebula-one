"""Retain published frontend dependency licences, identities and notice gaps."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def collect(source: Path, target: Path, component: str) -> dict:
    lock = json.loads((source / 'package-lock.json').read_text(encoding='utf-8'))
    records = []
    for location, pinned in sorted(lock['packages'].items()):
        if not location or pinned.get('dev'):
            continue
        package = (source / location).resolve()
        package.relative_to((source / 'node_modules').resolve())
        metadata = json.loads((package / 'package.json').read_text(encoding='utf-8'))
        if metadata['version'] != pinned['version']:
            raise ValueError(f'Dependency differs from lock: {component}/{location}')
        licence = metadata.get('license') or pinned.get('license')
        if not licence:
            raise ValueError(f'Dependency has no licence declaration: {component}/{location}')
        destination = target / component / location.removeprefix('node_modules/')
        destination.mkdir(parents=True, exist_ok=True)
        record = {'name': metadata['name'], 'version': metadata['version'],
                  'license': licence, 'author': metadata.get('author'),
                  'repository': metadata.get('repository'),
                  'integrity': pinned.get('integrity'), 'files': []}
        originals = [file for file in package.iterdir() if file.is_file()
                     and file.name.lower().startswith(('license', 'copying', 'notice'))]
        record['license_text_present'] = bool(originals)
        if not originals:
            originals = [file for file in package.iterdir() if file.is_file()
                         and file.name.lower().startswith('readme')]
            record['notice_gap'] = 'Published package declares a licence but contains no standalone licence text; original README and author declaration retained.'
        for file in originals:
            copied = destination / file.name
            shutil.copy2(file, copied)
            record['files'].append({'path': copied.relative_to(target).as_posix(),
                                    'sha256': hashlib.sha256(copied.read_bytes()).hexdigest()})
        records.append(record)
    return {'component': component,
            'lock_sha256': hashlib.sha256((source / 'package-lock.json').read_bytes()).hexdigest(),
            'dependencies': records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--one-web', required=True, type=Path)
    parser.add_argument('--lca-web', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    reports = [collect(args.one_web, args.output, 'one-web'),
               collect(args.lca_web, args.output, 'lca-web')]
    (args.output / 'javascript-dependencies.json').write_text(
        json.dumps(reports, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    gaps = [(report['component'], item['name'], item['version']) for report in reports
            for item in report['dependencies'] if not item['license_text_present']]
    for component, name, version in gaps:
        print(f'NOTICE GAP: {component} {name}@{version}: upstream package has no standalone licence text')
    print(f'Retained {sum(len(report["dependencies"]) for report in reports)} frontend dependency records')


if __name__ == '__main__':
    main()
