"""Frozen application entry: writable state is outside immutable resources."""
from __future__ import annotations

import os
from pathlib import Path


def main():
    root = Path(os.environ["NEBULA_ONE_DESKTOP_RESOURCES"]).resolve()
    data = Path(os.environ["NEBULA_ONE_DESKTOP_DATA"]).resolve()
    data.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    os.environ.update({
        "NEBULA_ONE_HOST": "127.0.0.1",
        "NEBULA_ONE_DATABASE_URL": "sqlite:///" + (data / "nebula-one.db").as_posix(),
        "NEBULA_LCA_BASE_URL": "http://nebula-lca.desktop.invalid",
        "NEBULA_LCA_TIMEOUT_SECONDS": "180",
        "NEBULA_ONE_CASEPACK_ROOTS": str(root / "cases"),
        "NEBULA_ONE_WEB_ROOT": str(root / "web"),
        "NEBULA_ONE_SEED_AUTOLOAD_FILE": str(root / "config/steel-demo.json"),
        "NEBULA_ONE_RELEASE_CATALOG_FILE": str(root / "config/public-catalog.v1.json"),
    })
    from .seeds.prepare_steel_catalog import main as prepare
    prepare()
    from .__main__ import main as serve
    serve()


if __name__ == "__main__":
    main()
