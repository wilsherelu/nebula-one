from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import Settings

# how long a boot waits for another boot's schema work or a running seed install to commit
SCHEMA_PREP_TIMEOUT_SECONDS = 60.0


class Base(DeclarativeBase):
    pass


class DatabaseSchemaError(RuntimeError):
    def __init__(self, *, current_revision: str | None, expected_revision: str) -> None:
        self.current_revision = current_revision
        self.expected_revision = expected_revision
        current = current_revision or "unversioned"
        super().__init__(
            "database schema is not at the required migration head "
            f"(current={current}, expected={expected_revision}); "
            "run 'alembic upgrade head' before starting Nebula One"
        )


def migration_script_location() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def migration_head_revision() -> str:
    config = Config()
    config.set_main_option("script_location", str(migration_script_location()))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError("Nebula One requires exactly one Alembic migration head")
    return heads[0]


class Database:
    def __init__(self, settings: Settings) -> None:
        settings.prepare_local_paths()
        connect_args = (
            # the default five-second busy wait is shorter than one seed install, so a second
            # boot of the same deployment would fail on a lock the first boot still holds
            {"check_same_thread": False, "timeout": SCHEMA_PREP_TIMEOUT_SECONDS}
            if settings.database_url.startswith("sqlite")
            else {}
        )
        self.engine = create_engine(
            settings.database_url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    def prepare_schema(self) -> None:
        if self.engine.dialect.name == "sqlite":
            with self._sqlite_schema_lock():
                self.create_schema()
            return
        if self.engine.dialect.name != "postgresql":
            raise RuntimeError(
                f"unsupported production database dialect: {self.engine.dialect.name}"
            )
        self.assert_schema_current()

    @contextmanager
    def _sqlite_schema_lock(self) -> Iterator[None]:
        """Let only one process at a time build or patch the schema of one SQLite file.

        The lock lives in a sidecar database on purpose: SQLite refuses a second writer even
        inside the same process, so a lock taken on the main file would starve the DDL this
        call is about to run against it.
        """
        target = self.engine.url.database
        if not target or target == ":memory:":
            yield
            return
        lock_path = Path(target).with_name(Path(target).name + ".lock")
        lock_engine = create_engine(
            f"sqlite:///{lock_path.as_posix()}",
            connect_args={"timeout": SCHEMA_PREP_TIMEOUT_SECONDS},
        )
        connection = lock_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            connection.exec_driver_sql("BEGIN EXCLUSIVE")
            yield
        finally:
            connection.close()
            lock_engine.dispose()

    def create_schema(self) -> None:
        if self.engine.dialect.name != "sqlite":
            raise RuntimeError(
                "automatic schema creation is limited to SQLite; "
                "use 'alembic upgrade head' for production databases"
            )
        from . import models  # noqa: F401
        from . import runtime_models  # noqa: F401

        Base.metadata.create_all(self.engine)
        columns = {
            item["name"] for item in inspect(self.engine).get_columns("analysis_runs")
        }
        if "system_revision_id" not in columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE analysis_runs ADD COLUMN "
                        "system_revision_id VARCHAR(36) REFERENCES system_revisions(id)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_analysis_runs_system_revision_id "
                        "ON analysis_runs (system_revision_id)"
                    )
                )
        self._prepare_sqlite_run_idempotency()
        self._prepare_sqlite_outbox_result_ref()
        self._prepare_sqlite_version_model_processing_ref()
        self._prepare_sqlite_version_semantics()
        operation_columns = {
            item["name"]
            for item in inspect(self.engine).get_columns("model_operations")
        }
        if "operation_batch_id" not in operation_columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE model_operations ADD COLUMN "
                        "operation_batch_id VARCHAR(36) REFERENCES operation_batches(id)"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE model_operations ADD COLUMN "
                        "batch_sequence INTEGER NOT NULL DEFAULT 0"
                    )
                )
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_model_operations_operation_batch_id "
                        "ON model_operations (operation_batch_id)"
                    )
                )

    def _prepare_sqlite_run_idempotency(self) -> None:
        table_scopes = (
            ("analysis_runs", "system_model_id", "uq_analysis_run_idempotency"),
            (
                "scenario_comparison_runs",
                "comparison_id",
                "uq_scenario_comparison_run_idempotency",
            ),
        )
        schema = inspect(self.engine)
        with self.engine.begin() as connection:
            for table_name, scope_column, index_name in table_scopes:
                columns = {
                    item["name"] for item in schema.get_columns(table_name)
                }
                if "idempotency_key" not in columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN "
                            "idempotency_key VARCHAR(128)"
                        )
                    )
                if "request_sha256" not in columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN "
                            "request_sha256 VARCHAR(64)"
                        )
                    )
                connection.execute(
                    text(
                        f"UPDATE {table_name} SET "
                        "idempotency_key = coalesce("
                        "idempotency_key, 'legacy:' || id), "
                        "request_sha256 = coalesce("
                        "request_sha256, replace(id, '-', '') || "
                        "replace(id, '-', '')) "
                        "WHERE idempotency_key IS NULL OR request_sha256 IS NULL"
                    )
                )
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                        f"ON {table_name} ({scope_column}, idempotency_key)"
                    )
                )

    def _prepare_sqlite_outbox_result_ref(self) -> None:
        schema = inspect(self.engine)
        if "outbox_events" not in schema.get_table_names():
            return
        columns = {
            item["name"] for item in schema.get_columns("outbox_events")
        }
        if "result_ref" not in columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE outbox_events ADD COLUMN "
                        "result_ref JSON NOT NULL DEFAULT '{}'"
                    )
                )

    def _prepare_sqlite_version_model_processing_ref(self) -> None:
        """Add the variant's bound processing-package column to an already-created versions table.

        ``create_all`` only builds missing tables, never new columns on existing ones, so a nullable
        column added to the model after the SQLite runtime table first came up must be reconciled here
        - the same way prior runtimes pick up their added columns - or a variant's exact binding has
        nowhere to persist on a shared database that predates the feature.
        """
        schema = inspect(self.engine)
        if "calculation_method_versions" not in schema.get_table_names():
            return
        columns = {
            item["name"]
            for item in schema.get_columns("calculation_method_versions")
        }
        if "model_processing_rules_ref" not in columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE calculation_method_versions ADD COLUMN "
                        "model_processing_rules_ref JSON"
                    )
                )

    def _prepare_sqlite_version_semantics(self) -> None:
        """Add the explicit method-version semantics column to an already-created versions table.

        Same rule as the other added columns: ``create_all`` never alters an existing table, so a
        shared SQLite database that predates flow-tag schemes must be reconciled before a tag
        version can persist. The column is nullable, so every historical row keeps the legacy
        reading.
        """
        schema = inspect(self.engine)
        if "calculation_method_versions" not in schema.get_table_names():
            return
        columns = {
            item["name"]
            for item in schema.get_columns("calculation_method_versions")
        }
        if "semantics" not in columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE calculation_method_versions ADD COLUMN "
                        "semantics VARCHAR(32)"
                    )
                )

    def current_schema_revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def assert_schema_current(self) -> None:
        expected = migration_head_revision()
        current = self.current_schema_revision()
        if current != expected:
            raise DatabaseSchemaError(
                current_revision=current,
                expected_revision=expected,
            )

    def dispose(self) -> None:
        self.engine.dispose()

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True

    @contextmanager
    def session(self) -> Iterator[Session]:
        db = self.session_factory()
        try:
            yield db
        finally:
            db.close()
