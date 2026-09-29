from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = "sqlite:///./runtime/nebula-one.db"
    nebula_lca_base_url: str = "http://127.0.0.1:8001"
    nebula_lca_timeout_seconds: float = 30.0
    profile_file: str | None = None
    casepack_roots: tuple[str, ...] = ("cases",)
    web_root: str | None = None
    seed_autoload_file: str | None = None
    release_catalog_file: str | None = None
    native_climate_contract_file: str | None = None
    native_inventory_contract_file: str | None = None
    nebula_lca_editor_url: str | None = None
    nebula_lca_trusted_source_urls: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        profile_file = os.getenv("NEBULA_ONE_PROFILE_FILE", "").strip() or None
        configured_casepack_roots = tuple(
            item.strip()
            for item in os.getenv("NEBULA_ONE_CASEPACK_ROOTS", "cases").split(os.pathsep)
            if item.strip()
        )
        return cls(
            database_url=os.getenv(
                "NEBULA_ONE_DATABASE_URL", "sqlite:///./runtime/nebula-one.db"
            ).strip(),
            nebula_lca_base_url=os.getenv(
                "NEBULA_LCA_BASE_URL", "http://127.0.0.1:8001"
            ).strip(),
            nebula_lca_timeout_seconds=float(
                os.getenv("NEBULA_LCA_TIMEOUT_SECONDS", "30")
            ),
            profile_file=profile_file,
            casepack_roots=configured_casepack_roots,
            web_root=os.getenv("NEBULA_ONE_WEB_ROOT", "").strip() or None,
            seed_autoload_file=os.getenv("NEBULA_ONE_SEED_AUTOLOAD_FILE", "").strip() or None,
            release_catalog_file=os.getenv("NEBULA_ONE_RELEASE_CATALOG_FILE", "").strip() or None,
            native_climate_contract_file=os.getenv("NEBULA_ONE_NATIVE_CLIMATE_CONTRACT_FILE", "").strip() or None,
            native_inventory_contract_file=os.getenv("NEBULA_ONE_NATIVE_INVENTORY_CONTRACT_FILE", "").strip() or None,
            nebula_lca_editor_url=os.getenv("NEBULA_LCA_EDITOR_URL", "").strip() or None,
            nebula_lca_trusted_source_urls=tuple(
                item.strip().rstrip("/") for item in os.getenv("NEBULA_LCA_TRUSTED_SOURCE_URLS", "").split(",")
                if item.strip()
            ),
        )

    def prepare_local_paths(self) -> None:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return
        raw_path = self.database_url[len(prefix) :]
        if raw_path == ":memory:" or not raw_path:
            return
        Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
