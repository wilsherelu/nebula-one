"""Retain published frontend dependency licences, identities and notice gaps."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def _retain(component: str, target: Path, package: Path, location: str, version: str,
            integrity: str | None, lock_licence: str | None) -> dict:
    metadata = json.loads((package / 'package.json').read_text(encoding='utf-8'))
    if metadata['version'] != version:
        raise ValueError(f'Dependency differs from lock: {component}/{location}')
    licence = metadata.get('license') or lock_licence
    if not licence:
        raise ValueError(f'Dependency has no licence declaration: {component}/{location}')
    destination = target / component / location.removeprefix('node_modules/')
    destination.mkdir(parents=True, exist_ok=True)
    record = {'name': metadata['name'], 'version': metadata['version'],
              'license': licence, 'author': metadata.get('author'),
              'repository': metadata.get('repository'),
              'integrity': integrity, 'files': []}
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
    return record


def _collect_npm(source: Path, target: Path, component: str) -> dict:
    lock_path = source / 'package-lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    node_modules = (source / 'node_modules').resolve()
    records = []
    for location, pinned in sorted(lock['packages'].items()):
        if not location or pinned.get('dev'):
            continue
        package = (source / location).resolve()
        package.relative_to(node_modules)
        records.append(_retain(component, target, package, location, pinned['version'],
                               pinned.get('integrity'), pinned.get('license')))
    return {'component': component, 'lockfile': lock_path.name,
            'lock_sha256': hashlib.sha256(lock_path.read_bytes()).hexdigest(),
            'dependencies': records}


def _pnpm_production_identities(lock: dict) -> list[tuple[str, str]]:
    """(name, version) of every production dependency reachable in a pnpm lockfile.

    Snapshots are keyed by their full peer-resolved suffix, so traversal keeps that key while the
    identity reported to the reader is the bare name and version. Dev-only trees are never entered:
    they are not bundled, and listing them would misstate what the package ships.
    """
    importer = (lock.get('importers') or {}).get('.') or {}
    snapshots = lock.get('snapshots') or {}
    queue = [(f'{name}@{spec["version"]}', name, str(spec['version']).split('(', 1)[0])
             for section in ('dependencies', 'optionalDependencies')
             for name, spec in sorted((importer.get(section) or {}).items())]
    identities: dict[tuple[str, str], None] = {}
    seen: set[str] = set()
    while queue:
        key, name, version = queue.pop(0)
        if key in seen:
            continue
        seen.add(key)
        identities.setdefault((name, version), None)
        snapshot = snapshots.get(key) or {}
        for section in ('dependencies', 'optionalDependencies'):
            for child_name, child in sorted((snapshot.get(section) or {}).items()):
                if not isinstance(child, str):
                    continue
                queue.append((f'{child_name}@{child}', child_name, child.split('(', 1)[0]))
    return list(identities)


def _pnpm_installed_index(source: Path) -> dict[tuple[str, str], Path]:
    """(name, version) -> installed dir, over the hoisted links and the pnpm content store."""
    root = source / 'node_modules'
    bases = [root]
    store = root / '.pnpm'
    if store.is_dir():
        bases += [entry / 'node_modules' for entry in sorted(store.iterdir()) if entry.is_dir()]
    index: dict[tuple[str, str], Path] = {}
    for base in bases:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name.startswith('.') or not entry.is_dir():
                continue
            children = ([(f'{entry.name}/{child.name}', child)
                         for child in sorted(entry.iterdir()) if child.is_dir()]
                        if entry.name.startswith('@') else [(entry.name, entry)])
            for name, directory in children:
                manifest = directory / 'package.json'
                if not manifest.is_file():
                    continue
                try:
                    version = json.loads(manifest.read_text(encoding='utf-8')).get('version')
                except json.JSONDecodeError:
                    continue
                if version:
                    index.setdefault((name, version), directory.resolve())
    return index


def _collect_pnpm(source: Path, target: Path, component: str) -> dict:
    try:
        import yaml
    except ModuleNotFoundError as error:
        raise RuntimeError('PyYAML is required to retain licences from a pnpm lockfile') from error
    lock_path = source / 'pnpm-lock.yaml'
    lock = yaml.safe_load(lock_path.read_text(encoding='utf-8'))
    packages = lock.get('packages') or {}
    installed = _pnpm_installed_index(source)
    identities = _pnpm_production_identities(lock)
    # One name can appear at several versions in a production graph; only then does the retained
    # path need the version to stay unique.
    versions_per_name: dict[str, int] = {}
    for name, _ in identities:
        versions_per_name[name] = versions_per_name.get(name, 0) + 1
    records = []
    for name, version in sorted(identities):
        package = installed.get((name, version))
        if package is None:
            raise FileNotFoundError(
                f'Production dependency is not installed, so its licence cannot be retained: '
                f'{component}/{name}@{version} (run the package manager install for {source})')
        location = f'node_modules/{name}' if versions_per_name[name] == 1 else f'node_modules/{name}-{version}'
        resolution = (packages.get(f'{name}@{version}') or {}).get('resolution') or {}
        records.append(_retain(component, target, package, location, version,
                               resolution.get('integrity'), (packages.get(f'{name}@{version}') or {}).get('license')))
    return {'component': component, 'lockfile': lock_path.name,
            'lock_sha256': hashlib.sha256(lock_path.read_bytes()).hexdigest(),
            'dependencies': records}


def collect(source: Path, target: Path, component: str) -> dict:
    if (source / 'package-lock.json').is_file():
        return _collect_npm(source, target, component)
    if (source / 'pnpm-lock.yaml').is_file():
        return _collect_pnpm(source, target, component)
    raise FileNotFoundError(
        f'No supported dependency lockfile in {source}: expected package-lock.json or pnpm-lock.yaml')


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
