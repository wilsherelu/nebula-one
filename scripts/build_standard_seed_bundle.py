from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from nebula_one.seeds import standard_seed_bundle  # noqa: E402

BuildError = standard_seed_bundle.BuildError
SeedBuild = standard_seed_bundle.SeedBuild


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=standard_seed_bundle.__doc__)
    parser.add_argument("--seed", default="iron-steel-bf-bof-crude-steel", help="directory under cases/standard-lca-seeds")
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=None,
        help="build this seed directory instead, for a scratch copy or a mutation harness",
    )
    parser.add_argument("--write-pins", action="store_true", help="store the computed digests in seed.json")
    parser.add_argument("--validate-only", action="store_true", help="run every check without writing build output")
    args = parser.parse_args(argv)

    seed_dir = standard_seed_bundle.resolve_seed_directory(args.seed, args.seed_dir)
    try:
        build = SeedBuild(seed_dir)
        if args.write_pins:
            if build.write_pins():
                print("pins written to", seed_dir / "seed.json")
            else:
                print("pins already current")
            build = SeedBuild(seed_dir)
        if args.validate_only:
            build.validate()
            print(f"validated {build.seed_id}@{build.version} bundle_content_sha256={build.pins()['bundle_content_sha256']}")
            return 0
        report = build.build()
    except BuildError as error:
        print(f"BUILD REFUSED: {error}", file=sys.stderr)
        return 1
    except FileNotFoundError as error:
        print(f"BUILD REFUSED: MISSING_FILE {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "seed": f"{report['seed_id']}@{report['seed_version']}",
                "bundle_content_sha256": report["bundle_content_sha256"],
                "zip": report["zip_path"],
                "zip_sha256": report["zip_sha256"],
                "zip_bytes": report["zip_bytes"],
                "entries": len(report["manifest"]["content"]),
                "counts": report["manifest"]["counts"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
