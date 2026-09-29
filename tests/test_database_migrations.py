from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from nebula_one import models, runtime_models  # noqa: F401
from nebula_one.config import Settings
from nebula_one.database import (
    Base,
    Database,
    DatabaseSchemaError,
    migration_head_revision,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_initial_migration_matches_current_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NEBULA_ONE_DATABASE_URL", raising=False)
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = _alembic_config(database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
        assert actual_tables == set(Base.metadata.tables)
        revision_constraints = {
            item["name"] for item in inspector.get_unique_constraints("system_revisions")
        }
        assert "uq_system_revision_number" in revision_constraints
        batch_constraints = {
            item["name"] for item in inspector.get_unique_constraints("operation_batches")
        }
        assert "uq_operation_batch_idempotency" in batch_constraints
        binding_column_details = {
            item["name"]: item for item in inspector.get_columns("system_bindings")
        }
        binding_columns = set(binding_column_details)
        assert {
            "application_id",
            "binding_id",
            "role",
            "system_model_id",
            "system_revision_id",
            "solved_snapshot_id",
            "study_frame_id",
            "reporting_period_id",
            "organizational_boundary_id",
            "demand",
            "capabilities",
            "dependencies",
            "content_sha256",
            "status",
        } <= binding_columns
        assert binding_column_details["system_revision_id"]["nullable"] is True
        assert binding_column_details["solved_snapshot_id"]["nullable"] is True
        binding_constraints = {
            item["name"]
            for item in inspector.get_unique_constraints("system_bindings")
        }
        assert binding_constraints == {
            "uq_system_binding_identity",
            "uq_system_binding_role",
        }
        binding_foreign_keys = {
            (tuple(item["constrained_columns"]), item["referred_table"])
            for item in inspector.get_foreign_keys("system_bindings")
        }
        assert binding_foreign_keys == {
            (("application_id",), "applications"),
            (("system_model_id",), "system_models"),
            (("system_revision_id",), "system_revisions"),
            (("solved_snapshot_id",), "solved_system_snapshots"),
            (("reporting_period_id",), "periods"),
            (("organizational_boundary_id",), "boundary_definitions"),
        }
        source_columns = {
            item["name"] for item in inspector.get_columns("model_sources")
        }
        assert {
            "application_id",
            "system_model_id",
            "source_type",
            "file_sha256",
            "upstream_project_id",
            "upstream_version",
            "graph_sha256",
            "import_receipt",
            "candidate_versions",
            "external_dependencies",
            "issues",
            "content_sha256",
        } <= source_columns
        assert {
            item["name"] for item in inspector.get_unique_constraints("model_sources")
        } == {"uq_model_source_system_model"}
        installation_columns = {
            item["name"] for item in inspector.get_columns("seed_installations")
        }
        assert {
            "seed_id",
            "seed_version",
            "install_key",
            "bundle_content_sha256",
            "engine_db_digest",
            "engine_openapi_version",
            "status",
            "stage_receipts",
            "engine_project_id",
            "engine_graph_hash",
            "role_instance_map",
            "verification",
        } <= installation_columns
        assert {
            item["name"] for item in inspector.get_unique_constraints("seed_installations")
        } == {"uq_seed_installation_key", "uq_seed_installation_engine_version"}
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision()
                == migration_head_revision()
            )
    finally:
        engine.dispose()

    command.check(config)
    command.downgrade(config, "base")
    downgraded_engine = create_engine(database_url)
    try:
        assert set(inspect(downgraded_engine).get_table_names()) <= {
            "alembic_version"
        }
    finally:
        downgraded_engine.dispose()
    command.upgrade(config, "head")


def test_schema_guard_rejects_unversioned_database(tmp_path) -> None:
    database = Database(
        Settings(database_url=f"sqlite:///{(tmp_path / 'unversioned.db').as_posix()}")
    )
    try:
        try:
            database.assert_schema_current()
        except DatabaseSchemaError as exc:
            assert exc.current_revision is None
            assert exc.expected_revision == migration_head_revision()
            assert "alembic upgrade head" in str(exc)
        else:
            raise AssertionError("unversioned database unexpectedly passed schema guard")
    finally:
        database.dispose()


def test_schema_guard_accepts_migrated_database(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NEBULA_ONE_DATABASE_URL", raising=False)
    database_path = tmp_path / "current.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    command.upgrade(_alembic_config(database_url), "head")
    database = Database(Settings(database_url=database_url))
    try:
        database.assert_schema_current()
    finally:
        database.dispose()


def test_schema_preparation_keeps_sqlite_auto_create_and_postgres_guard(
    tmp_path,
) -> None:
    sqlite_database = object.__new__(Database)
    sqlite_database.engine = SimpleNamespace(
        dialect=SimpleNamespace(name="sqlite"),
        url=SimpleNamespace(database=str(tmp_path / "prepared.db")),
    )
    sqlite_database.create_schema = Mock()
    sqlite_database.assert_schema_current = Mock()
    sqlite_database.prepare_schema()
    sqlite_database.create_schema.assert_called_once_with()
    sqlite_database.assert_schema_current.assert_not_called()
    # the route is only half the promise: the schema work has to run inside the lock, or a
    # second boot of the same file builds the tables it is about to build
    assert (tmp_path / "prepared.db.lock").exists()

    postgres_database = object.__new__(Database)
    postgres_database.engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        url=SimpleNamespace(database=None),
    )
    postgres_database.create_schema = Mock()
    postgres_database.assert_schema_current = Mock()
    postgres_database.prepare_schema()
    postgres_database.create_schema.assert_not_called()
    postgres_database.assert_schema_current.assert_called_once_with()


def test_sqlite_auto_create_upgrades_legacy_run_identity_columns(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("NEBULA_ONE_DATABASE_URL", raising=False)
    database_path = tmp_path / "legacy-local.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    command.upgrade(_alembic_config(database_url), "20260831_01")
    legacy_analysis_id = "11111111-1111-1111-1111-111111111111"
    legacy_comparison_id = "22222222-2222-2222-2222-222222222222"
    legacy_engine = create_engine(database_url)
    try:
        with legacy_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO analysis_runs "
                    "(id, system_model_id, system_revision_id, capability_key, "
                    "parameters, status, model_graph_sha256, provider_receipt, "
                    "result, error, created_at, started_at, completed_at) VALUES "
                    "(:id, :model_id, NULL, 'mfa.declared.v1', '{}', 'succeeded', "
                    ":hash, '{}', '{}', NULL, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": legacy_analysis_id,
                    "model_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "hash": "a" * 64,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO scenario_comparison_runs "
                    "(id, application_id, comparison_id, baseline_scenario_id, "
                    "status, request, scenario_results, metrics, audit, error, "
                    "content_sha256, created_at, completed_at) VALUES "
                    "(:id, :application_id, :comparison_id, :scenario_id, "
                    "'succeeded', '{}', '[]', '[]', '{}', '{}', :hash, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": legacy_comparison_id,
                    "application_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "comparison_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                    "scenario_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                    "hash": "b" * 64,
                },
            )
    finally:
        legacy_engine.dispose()

    database = Database(Settings(database_url=database_url))
    try:
        database.create_schema()
        inspector = inspect(database.engine)
        for table_name, index_name in (
            ("analysis_runs", "uq_analysis_run_idempotency"),
            (
                "scenario_comparison_runs",
                "uq_scenario_comparison_run_idempotency",
            ),
        ):
            columns = {item["name"] for item in inspector.get_columns(table_name)}
            assert {"idempotency_key", "request_sha256"} <= columns
            indexes = {item["name"] for item in inspector.get_indexes(table_name)}
            assert index_name in indexes
        with database.engine.connect() as connection:
            analysis_identity = connection.execute(
                text(
                    "SELECT idempotency_key, request_sha256 FROM analysis_runs "
                    "WHERE id = :id"
                ),
                {"id": legacy_analysis_id},
            ).one()
            comparison_identity = connection.execute(
                text(
                    "SELECT idempotency_key, request_sha256 "
                    "FROM scenario_comparison_runs WHERE id = :id"
                ),
                {"id": legacy_comparison_id},
            ).one()
        assert analysis_identity == (
            f"legacy:{legacy_analysis_id}",
            legacy_analysis_id.replace("-", "") * 2,
        )
        assert comparison_identity == (
            f"legacy:{legacy_comparison_id}",
            legacy_comparison_id.replace("-", "") * 2,
        )
    finally:
        database.dispose()
