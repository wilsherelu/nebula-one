from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


class ProductBlueprint:
    def __init__(self) -> None:
        path = files("nebula_one").joinpath("resources/product_blueprint.json")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot load product blueprint from {path}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("core_objects"), list):
            raise RuntimeError("product blueprint must define core_objects")
        self._payload: dict[str, Any] = payload

    def get(self) -> dict[str, Any]:
        return self._payload
