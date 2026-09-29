from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
import threading
import time
from uuid import uuid4

from alembic import command
from alembic.config import Config
import httpx
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
import uvicorn

from nebula_one.config import Settings
from nebula_one.database import (
    Database,
    DatabaseSchemaError,
    migration_head_revision,
)
from nebula_one.hashing import canonical_graph_sha256
from nebula_one.main import create_app


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: dict) -> None:
    path.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _database_label(database_url: str) -> dict:
    parsed = make_url(database_url)
    return {
        "driver": parsed.drivername,
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
    }


def _assert_empty_database(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        tables = inspect(engine).get_table_names()
    finally:
        engine.dispose()
    if tables:
        raise RuntimeError(
            "PostgreSQL migration smoke requires a dedicated empty database; "
            f"found {len(tables)} existing tables"
        )


def _inline_graph() -> dict:
    return {
        "functionalUnit": "1 kg migration-smoke product",
        "nodes": [
            {
                "id": "migration-smoke-process",
                "node_kind": "unit_process",
                "mode": "normalized",
                "process_uuid": "migration-smoke-process",
                "name": "Migration smoke process",
                "location": "GLO",
                "reference_product": "migration-smoke-product",
                "inputs": [],
                "outputs": [
                    {
                        "id": "migration-smoke-product-out",
                        "flowUuid": "migration-smoke-product",
                        "name": "migration-smoke product",
                        "unit": "kg",
                        "unitGroup": "Units of mass",
                        "amount": 1.0,
                        "type": "technosphere",
                        "direction": "output",
                    }
                ],
                "emissions": [],
            }
        ],
        "exchanges": [],
        "metadata": {"case": "postgres-migration-smoke"},
    }


def _run_http_smoke(database_url: str) -> dict:
    app = create_app(
        Settings(
            database_url=database_url,
            nebula_lca_base_url="http://127.0.0.1:1",
            nebula_lca_timeout_seconds=1,
            casepack_roots=(),
        )
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
    )
    thread.start()
    graph = _inline_graph()
    try:
        deadline = time.monotonic() + 15
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
        ) as client:
            while True:
                try:
                    health = client.get("/health")
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("PostgreSQL HTTP smoke server did not start")
                time.sleep(0.05)
            application = client.post(
                "/api/v1/applications",
                json={
                    "name": "PostgreSQL migration smoke",
                    "application_type": "system_analysis",
                    "context": {"acceptance": "isolated_postgresql"},
                },
            )
            if application.status_code != 201:
                raise RuntimeError(f"application create failed: {application.text}")
            application_id = application.json()["id"]
            model = client.post(
                f"/api/v1/applications/{application_id}/system-models/inline",
                json={
                    "name": "PostgreSQL inline model",
                    "provider": "nebula_lca",
                    "source_id": "casepack:postgres-migration-smoke",
                    "source_version": 1,
                    "expected_graph_sha256": canonical_graph_sha256(graph),
                    "graph": graph,
                },
            )
            if model.status_code != 201:
                raise RuntimeError(f"inline model create failed: {model.text}")
            model_payload = model.json()
            revisions = client.get(
                f"/api/v1/system-models/{model_payload['id']}/revisions"
            )
            if revisions.status_code != 200:
                raise RuntimeError(f"revision list failed: {revisions.text}")
            return {
                "health_status": health.status_code,
                "application_status": application.status_code,
                "application_id": application_id,
                "system_model_status": model.status_code,
                "system_model_id": model_payload["id"],
                "base_revision_id": model_payload["upstream_receipt"][
                    "base_revision_id"
                ],
                "revision_numbers": [
                    item["revision_number"] for item in revisions.json()
                ],
            }
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("PostgreSQL HTTP smoke server did not stop")


def _verify_persistence_and_unique_constraint(
    database_url: str, http_result: dict
) -> dict:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            application_count = connection.scalar(
                text("SELECT count(*) FROM applications WHERE id = :id"),
                {"id": http_result["application_id"]},
            )
            revision_count = connection.scalar(
                text(
                    "SELECT count(*) FROM system_revisions "
                    "WHERE system_model_id = :system_model_id"
                ),
                {"system_model_id": http_result["system_model_id"]},
            )
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text(
                        "INSERT INTO system_revisions "
                        "(id, system_model_id, parent_revision_id, revision_number, "
                        "label, revision_kind, graph_sha256, content_sha256, "
                        "graph_snapshot, application_context, status, publish_receipt, "
                        "created_at, published_at) "
                        "SELECT :duplicate_id, system_model_id, NULL, revision_number, "
                        ":label, revision_kind, graph_sha256, content_sha256, "
                        "graph_snapshot, application_context, status, publish_receipt, "
                        "created_at, published_at FROM system_revisions WHERE id = :source_id"
                    ),
                    {
                        "duplicate_id": str(uuid4()),
                        "label": "duplicate revision number probe",
                        "source_id": http_result["base_revision_id"],
                    },
                )
            except IntegrityError:
                transaction.rollback()
                duplicate_blocked = True
            else:
                transaction.rollback()
                duplicate_blocked = False
    finally:
        engine.dispose()
    if not duplicate_blocked:
        raise RuntimeError("revision-number unique constraint did not reject duplicate")
    return {
        "application_row_persisted": application_count == 1,
        "base_revision_row_persisted": revision_count == 1,
        "duplicate_revision_number_blocked": duplicate_blocked,
        "constraint_name": "uq_system_revision_number",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate and exercise a dedicated empty PostgreSQL database."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    label = _database_label(args.database_url)
    if not label["driver"].startswith("postgresql"):
        raise RuntimeError("PostgreSQL migration smoke only accepts PostgreSQL URLs")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise RuntimeError("output directory must be absent or empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    _assert_empty_database(args.database_url)
    unversioned_database = Database(
        Settings(database_url=args.database_url, casepack_roots=())
    )
    try:
        try:
            unversioned_database.assert_schema_current()
        except DatabaseSchemaError as exc:
            pre_migration_guard = {
                "status": "passed",
                "current_revision": exc.current_revision,
                "expected_revision": exc.expected_revision,
            }
        else:
            raise RuntimeError("unversioned PostgreSQL database passed startup guard")
    finally:
        unversioned_database.dispose()
    config = _alembic_config(args.database_url)
    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "base")
    round_trip_engine = create_engine(args.database_url, pool_pre_ping=True)
    try:
        remaining_after_downgrade = set(
            inspect(round_trip_engine).get_table_names()
        ) - {"alembic_version"}
    finally:
        round_trip_engine.dispose()
    if remaining_after_downgrade:
        raise RuntimeError("migration downgrade left application tables behind")
    command.upgrade(config, "head")
    database = Database(Settings(database_url=args.database_url, casepack_roots=()))
    try:
        database.assert_schema_current()
        current_revision = database.current_schema_revision()
    finally:
        database.dispose()

    http_result = _run_http_smoke(args.database_url)
    persistence = _verify_persistence_and_unique_constraint(
        args.database_url, http_result
    )
    engine = create_engine(args.database_url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        table_count = len(inspector.get_table_names())
        with engine.connect() as connection:
            server_version = connection.scalar(text("SHOW server_version"))
    finally:
        engine.dispose()

    audit = {
        "schema_version": "nebula.postgresql-migration-smoke.v1",
        "status": "passed",
        "database": label,
        "server_version": server_version,
        "migration": {
            "pre_migration_guard": pre_migration_guard,
            "upgrade_check_downgrade_upgrade_round_trip": "passed",
            "current_revision": current_revision,
            "expected_head": migration_head_revision(),
            "table_count_including_alembic_version": table_count,
        },
        "http": http_result,
        "persistence": persistence,
        "claim_limits": [
            "the run uses a dedicated empty PostgreSQL database",
            "the smoke proves migration, HTTP persistence, and database uniqueness",
            "outbox, asynchronous execution, tenant isolation, and backup recovery are not covered",
        ],
    }
    audit_path = args.output_dir / "audit.json"
    _write_json(audit_path, audit)
    digest = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    (args.output_dir / "manifest.sha256").write_bytes(
        f"{digest}  audit.json\n".encode("ascii")
    )
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
