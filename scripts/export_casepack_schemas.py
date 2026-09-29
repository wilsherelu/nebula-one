from __future__ import annotations

import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from nebula_one.casepacks.contracts import contract_json_schemas  # noqa: E402


def main() -> None:
    output_dir = REPOSITORY_ROOT / "schemas" / "casepack"
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, schema in contract_json_schemas().items():
        destination = output_dir / filename
        destination.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(destination.relative_to(REPOSITORY_ROOT).as_posix())


if __name__ == "__main__":
    main()
