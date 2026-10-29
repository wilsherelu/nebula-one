"""Licence retention must follow whichever lockfile the frontend actually uses.

The LCA web moved to pnpm, so a collector that only reads package-lock.json cannot attest the
licences of the dependencies that ship inside the desktop payload.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from desktop.javascript_notices import collect

PNPM_LOCK = """\
lockfileVersion: '9.0'
importers:
  .:
    dependencies:
      react:
        specifier: ^19.0.0
        version: 19.0.0(peer@1.0.0)
    devDependencies:
      devonly:
        specifier: ^2.0.0
        version: 2.0.0
packages:
  react@19.0.0:
    resolution: {integrity: sha512-react}
  '@scope/tool@1.0.0':
    resolution: {integrity: sha512-tool}
  devonly@2.0.0:
    resolution: {integrity: sha512-devonly}
snapshots:
  react@19.0.0(peer@1.0.0):
    dependencies:
      '@scope/tool': 1.0.0
  '@scope/tool@1.0.0': {}
  devonly@2.0.0: {}
"""


def _install(source: Path, name: str, version: str, *, license_file: str | None = 'LICENSE',
             license_field: str | None = 'MIT') -> Path:
    directory = source / 'node_modules' / '.pnpm' / f"{name.replace('/', '+')}@{version}" \
        / 'node_modules' / name
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {'name': name, 'version': version}
    if license_field:
        manifest['license'] = license_field
    (directory / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    if license_file:
        (directory / license_file).write_text(f'{name} licence text\n', encoding='utf-8')
    return directory


def _pnpm_source(tmp_path: Path) -> Path:
    source = tmp_path / 'lca-web'
    source.mkdir(parents=True)
    (source / 'pnpm-lock.yaml').write_text(PNPM_LOCK, encoding='utf-8')
    _install(source, 'react', '19.0.0')
    _install(source, '@scope/tool', '1.0.0', license_file=None, license_field='Apache-2.0')
    (source / 'node_modules' / '.pnpm' / '@scope+tool@1.0.0' / 'node_modules' / '@scope' / 'tool'
     / 'README.md').write_text('author declaration\n', encoding='utf-8')
    _install(source, 'devonly', '2.0.0')
    return source


def test_pnpm_production_tree_is_retained_without_dev_dependencies(tmp_path) -> None:
    source = _pnpm_source(tmp_path)
    report = collect(source, tmp_path / 'out', 'lca-web')
    by_name = {item['name']: item for item in report['dependencies']}
    assert set(by_name) == {'react', '@scope/tool'}, 'dev-only trees must not be reported as shipped'
    assert report['lockfile'] == 'pnpm-lock.yaml'
    assert report['lock_sha256'] == hashlib.sha256((source / 'pnpm-lock.yaml').read_bytes()).hexdigest()
    assert by_name['react']['integrity'] == 'sha512-react'
    assert by_name['react']['license'] == 'MIT'
    assert by_name['react']['license_text_present'] is True
    retained = tmp_path / 'out' / 'lca-web' / 'react' / 'LICENSE'
    assert retained.is_file()
    assert by_name['react']['files'][0]['sha256'] == hashlib.sha256(retained.read_bytes()).hexdigest()


def test_pnpm_package_without_licence_text_reports_the_notice_gap(tmp_path) -> None:
    report = collect(_pnpm_source(tmp_path), tmp_path / 'out', 'lca-web')
    tool = next(item for item in report['dependencies'] if item['name'] == '@scope/tool')
    assert tool['license'] == 'Apache-2.0'
    assert tool['license_text_present'] is False
    assert tool['notice_gap']
    assert [Path(item['path']).name for item in tool['files']] == ['README.md']


def test_pnpm_version_drift_between_lock_and_installed_tree_is_refused(tmp_path) -> None:
    source = _pnpm_source(tmp_path)
    _install(source, 'react', '19.0.1')
    (source / 'node_modules' / '.pnpm' / 'react@19.0.0').rename(tmp_path / 'gone')
    with pytest.raises(FileNotFoundError, match='react@19.0.0'):
        collect(source, tmp_path / 'out', 'lca-web')


def test_pnpm_dependency_missing_from_the_install_is_refused(tmp_path) -> None:
    source = _pnpm_source(tmp_path)
    (source / 'node_modules' / '.pnpm' / '@scope+tool@1.0.0').rename(tmp_path / 'moved')
    with pytest.raises(FileNotFoundError, match='@scope/tool@1.0.0'):
        collect(source, tmp_path / 'out', 'lca-web')


def test_npm_lockfile_path_is_unchanged(tmp_path) -> None:
    source = tmp_path / 'one-web'
    package = _install(source, 'left-pad', '1.3.0')
    hoisted = source / 'node_modules' / 'left-pad'
    hoisted.parent.mkdir(parents=True, exist_ok=True)
    package.rename(hoisted)
    (source / 'package-lock.json').write_text(json.dumps({'packages': {
        '': {'name': 'one-web'},
        'node_modules/left-pad': {'version': '1.3.0', 'license': 'WTFPL', 'integrity': 'sha512-left'},
        'node_modules/devtool': {'version': '9.9.9', 'dev': True},
    }}), encoding='utf-8')
    report = collect(source, tmp_path / 'out', 'one-web')
    assert report['lockfile'] == 'package-lock.json'
    assert [item['name'] for item in report['dependencies']] == ['left-pad']
    assert report['dependencies'][0]['integrity'] == 'sha512-left'


def test_npm_lock_and_installed_version_drift_is_refused(tmp_path) -> None:
    source = tmp_path / 'drift'
    package = _install(source, 'left-pad', '1.3.0')
    hoisted = source / 'node_modules' / 'left-pad'
    package.rename(hoisted)
    (hoisted / 'package.json').write_text(
        json.dumps({'name': 'left-pad', 'version': '1.3.1', 'license': 'WTFPL'}), encoding='utf-8')
    (source / 'package-lock.json').write_text(json.dumps({'packages': {
        'node_modules/left-pad': {'version': '1.3.0', 'license': 'WTFPL'},
    }}), encoding='utf-8')
    with pytest.raises(ValueError, match='Dependency differs from lock'):
        collect(source, tmp_path / 'out', 'drift')


def test_a_frontend_without_any_lockfile_is_refused(tmp_path) -> None:
    source = tmp_path / 'bare'
    source.mkdir()
    with pytest.raises(FileNotFoundError, match='No supported dependency lockfile'):
        collect(source, tmp_path / 'out', 'bare')
