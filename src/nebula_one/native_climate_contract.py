"""The single pinned native-background climate contract One is allowed to consume.

Nebula LCA refuses to resolve a saved climate analysis through `active` or `latest`, and One must
not be able to either: the exact method package, runtime manifest and source snapshot hashes live in
this versioned resource rather than the adapter, a service or the browser, so a calculation records
the identity the source contract published instead of one an operator typed in.
"""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from .mapped_background_schemas import ProviderNativeBackgroundClimateRequest

CONTRACT_SCHEMA_VERSION = "nebula_one.native-background-climate-contract.v1"
_SOURCE_KEYS = ("repository", "commit", "document", "document_sha256")

class NativeClimateContract:
    def __init__(self, override_path: str | None = None) -> None:
        path = Path(
            override_path
            or files("nebula_one").joinpath("resources/native_background_climate.json")
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"cannot load the native background climate contract from {path}: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            raise RuntimeError(
                f"native background climate contract must declare {CONTRACT_SCHEMA_VERSION}"
            )
        source = payload.get("source_contract")
        if not isinstance(source, dict) or any(
            not str(source.get(key) or "").strip() for key in _SOURCE_KEYS
        ):
            raise RuntimeError(
                "the native background climate contract must cite its source commit and document hash"
            )
        self.source_contract = {key: str(source[key]).strip() for key in _SOURCE_KEYS}
        self.request_pin = ProviderNativeBackgroundClimateRequest.model_validate(
            payload.get("solve_request_pin")
        )
        request = payload.get("provider_solve_request")
        methods = request.get("lcia_methods") if isinstance(request, dict) else None
        if not isinstance(methods, list) or not methods or any(
            not isinstance(item, str) or not item.strip() for item in methods
        ):
            raise RuntimeError(
                "the native background climate contract must carry its provider lcia_methods selection"
            )
        self.lcia_methods = tuple(item.strip() for item in methods)

    def request_payload(self) -> dict[str, Any]:
        """The exact `native_background_climate` object to send with a provider solve."""
        return self.request_pin.model_dump(mode="json")

    def solve_methods(self) -> list[str]:
        """The method selection the contract's single indicator is reported under.

        Nebula LCA refuses a native climate solve under any other selection, so this is part of the
        pinned contract rather than something a caller chooses per request.
        """
        return list(self.lcia_methods)
