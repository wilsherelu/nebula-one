from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from nebula_one.adapters.nebula_lca import NebulaLCAClient  # noqa: E402
from nebula_one.config import Settings  # noqa: E402
from nebula_one.database import Database  # noqa: E402
from nebula_one.errors import DomainError  # noqa: E402
from nebula_one.models import SeedInstallation  # noqa: E402
from nebula_one.seeds import standard_seed_bundle  # noqa: E402
from nebula_one.services.seed_installation import (  # noqa: E402
    SeedInstallationService,
)
from nebula_one.services.system_models import SystemModelService  # noqa: E402


def _receipt(row: SeedInstallation) -> dict[str, object]:
    return {
        "installation_id": row.id,
        "seed": f"{row.seed_id}@{row.seed_version}",
        "status": row.status,
        "install_key": row.install_key,
        "bundle_content_sha256": row.bundle_content_sha256,
        "engine_base_url": row.engine_base_url,
        "engine_db_digest": row.engine_db_digest,
        "engine_openapi_version": row.engine_openapi_version,
        "engine_project_id": row.engine_project_id,
        "engine_graph_hash": row.engine_graph_hash,
        "zip_path": row.zip_path,
        "zip_sha256": row.zip_sha256,
        "application_id": row.application_id,
        "system_model_id": row.system_model_id,
        "system_revision_id": row.system_revision_id,
        "stage_receipts": row.stage_receipts,
        "verification": row.verification,
        "role_instance_map": row.role_instance_map,
        "failure": row.failure,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=SeedInstallationService.__doc__)
    parser.add_argument(
        "--seed", default="iron-steel-bf-bof-crude-steel", help="directory under cases/standard-lca-seeds"
    )
    parser.add_argument("--seed-dir", type=Path, default=None, help="install this seed directory instead")
    parser.add_argument("--engine-url", default=None, help="Nebula LCA base URL, defaults to the environment")
    parser.add_argument("--one-database", default=None, help="Nebula One database URL, defaults to the environment")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="run the build gates and stage the bundle without calling the engine at all",
    )
    parser.add_argument("--application-id", default=None, help="bind the verified model to this application")
    parser.add_argument(
        "--boundary",
        default=None,
        help="seed application key whose boundary file authorizes that binding",
    )
    parser.add_argument(
        "--declare",
        action="append",
        default=[],
        metavar="CLAUSE=VALUE",
        help=(
            "answer one undecided boundary item that requires a runtime declaration, "
            "keyed by its clause, e.g. --declare H-C12=sold"
        ),
    )
    args = parser.parse_args(argv)

    declarations: dict[str, str] = {}
    for item in args.declare:
        clause, separator, value = item.partition("=")
        if not separator or not clause.strip() or not value.strip():
            print(
                json.dumps({"refused": "--declare expects CLAUSE=VALUE", "given": item}),
                file=sys.stderr,
            )
            return 2
        if clause.strip() in declarations:
            print(
                json.dumps({"refused": "--declare given twice for one clause", "clause": clause.strip()}),
                file=sys.stderr,
            )
            return 2
        declarations[clause.strip()] = value.strip()

    settings = Settings.from_env()
    overrides: dict[str, str] = {}
    if args.engine_url:
        overrides["nebula_lca_base_url"] = args.engine_url
    if args.one_database:
        overrides["database_url"] = args.one_database
    if overrides:
        settings = replace(settings, **overrides)
    seed_dir = standard_seed_bundle.resolve_seed_directory(args.seed, args.seed_dir)

    database = Database(settings)
    if not args.validate_only:
        # the same schema preparation the application lifespan performs at startup
        database.prepare_schema()
    client = NebulaLCAClient(settings.nebula_lca_base_url, settings.nebula_lca_timeout_seconds)
    service = SeedInstallationService(database, client, SystemModelService(database, client))
    try:
        if args.validate_only:
            print(json.dumps(service.plan(seed_dir), indent=2, ensure_ascii=False))
            return 0
        row = service.install(
            seed_dir,
            application_id=args.application_id,
            boundary_key=args.boundary,
            declarations=declarations,
        )
        print(json.dumps(_receipt(row), indent=2, ensure_ascii=False))
        return 0
    except DomainError as error:
        print(
            json.dumps(
                {"refused": {"code": error.code, "message": error.message, "details": error.details}},
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        client.close()
        database.dispose()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
