"""Record frozen Python dependency identities and their distributed licence files."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys


def main():
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    records = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda item: item.metadata['Name'].lower()):
        name = distribution.metadata['Name']
        record = {'name':name, 'version':distribution.version,
                  'license':distribution.metadata.get('License-Expression') or distribution.metadata.get('License'),
                  'license_files':[]}
        for file in distribution.files or []:
            if file.name.lower().startswith(('license', 'copying', 'notice')):
                source = Path(distribution.locate_file(file))
                if not source.is_file():
                    continue
                destination = target / name / str(file).replace('..', '_')
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                record['license_files'].append(destination.relative_to(target).as_posix())
        records.append(record)
    (target / 'python-dependencies.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
