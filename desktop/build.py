"""Build existing backends and desktop resources with an isolated toolchain."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import venv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lca-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lca = args.lca_root.resolve()
    output = args.output.resolve()
    if output.is_relative_to(root) or output.is_relative_to(lca):
        raise ValueError('Installer output must be outside both source repositories')
    environment = root / 'build/desktop-venv'
    if not environment.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / 'Scripts/python.exe'
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(root / 'desktop/requirements-build.txt')], check=True)
    for working, spec, dist, build, imports in [
        (root, root / 'desktop/one.spec', root / 'build/desktop-backends', root / 'build/pyinstaller-one', root / 'src'),
        (lca / 'nebula-lca-api', lca / 'nebula-lca-api/pyinstaller/nebula-lca-public.spec', lca / 'build/desktop-backends', lca / 'build/pyinstaller-public', lca / 'nebula-lca-api'),
    ]:
        env = {**os.environ, 'PYTHONPATH': str(imports)}
        subprocess.run([str(python), '-m', 'PyInstaller', str(spec), '--distpath', str(dist),
                        '--workpath', str(build), '--noconfirm'], cwd=working, env=env, check=True)
    subprocess.run([str(python), str(root / 'desktop/build_payload.py'), '--lca-root', str(lca)], cwd=root, check=True)
    subprocess.run(['npm.cmd', 'ci', '--no-audit', '--no-fund'], cwd=root / 'desktop', check=True)
    # Local preview packages are unsigned. Do not require privileged symlink extraction
    # for signing helpers; formal signing is configured separately when publishing.
    subprocess.run(['npm.cmd', 'run', 'build', '--', '--config.win.signAndEditExecutable=false',
                    f'--config.directories.output={output}'], cwd=root / 'desktop', check=True)


if __name__ == '__main__':
    main()
