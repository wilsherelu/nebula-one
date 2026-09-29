"""Optional deployment pin for Nebula LCA's method-independent native inventory."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .mapped_background_schemas import ProviderNativeBackgroundInventoryRequest


class NativeInventoryContract:
    def __init__(self, path: str | None) -> None:
        self.request_pin: ProviderNativeBackgroundInventoryRequest | None = None
        if path is None:
            return
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot load native inventory contract from {source}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != "nebula_one.native-inventory-contract.v1":
            raise RuntimeError("native inventory contract has an unsupported schema")
        self.request_pin = ProviderNativeBackgroundInventoryRequest.model_validate(payload.get("solve_request_pin"))

    def request_payload(self) -> dict[str, Any]:
        if self.request_pin is None:
            raise RuntimeError("native inventory contract is not configured")
        return self.request_pin.model_dump(mode="json")
