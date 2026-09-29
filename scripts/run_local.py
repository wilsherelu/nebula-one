"""Start the source checkout with explicit application storage and a built web console.

The engine is a separate service. This command never starts it or changes its storage.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True, help='dedicated writable application data directory')
    parser.add_argument('--engine-url', required=True, help='URL of the separately configured Nebula LCA API')
    parser.add_argument('--port', type=int, default=8088)
    parser.add_argument('--editor-url', help='optional Nebula LCA editor base URL (separate from API)')
    parser.add_argument('--autoload', type=Path, help='optional reviewed seed installation manifest; enables model writes through the engine API')
    args = parser.parse_args()
    web = ROOT / 'web/dist'
    if not (web / 'index.html').is_file():
        parser.error('web/dist/index.html is missing; run npm ci and npm run build in web/ first')
    if args.autoload and not args.autoload.resolve().is_file():
        parser.error('autoload manifest does not exist')
    data = args.data_dir.resolve()
    env = os.environ.copy()
    env.update({
        'PYTHONPATH': str(ROOT / 'src'),
        'NEBULA_ONE_HOST': '127.0.0.1',
        'NEBULA_ONE_PORT': str(args.port),
        'NEBULA_ONE_DATABASE_URL': 'sqlite:///' + (data / 'nebula-one.db').as_posix(),
        'NEBULA_ONE_WEB_ROOT': str(web),
        'NEBULA_ONE_CASEPACK_ROOTS': str(ROOT / 'cases'),
        'NEBULA_LCA_BASE_URL': args.engine_url,
        'NEBULA_LCA_EDITOR_URL': args.editor_url or '',
        'NEBULA_ONE_SEED_AUTOLOAD_FILE': str(args.autoload.resolve()) if args.autoload else '',
    })
    print(f'Application: http://127.0.0.1:{args.port}\nStorage: {data}\nEngine: {args.engine_url}', flush=True)
    process = subprocess.Popen([sys.executable, '-B', '-m', 'nebula_one'], cwd=ROOT, env=env)
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
