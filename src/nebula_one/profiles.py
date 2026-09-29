from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from .errors import DomainError


class ApplicationProfiles:
    def __init__(self, override_path: str | None = None) -> None:
        path = (
            Path(override_path).expanduser().resolve()
            if override_path
            else files("nebula_one").joinpath("resources/application_profiles.json")
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot load application profiles from {path}: {exc}") from exc
        profiles = payload.get("profiles")
        if not isinstance(profiles, list):
            raise RuntimeError("application profile file must contain a profiles list")
        self.schema_version = str(payload.get("schema_version") or "")
        self._profiles: dict[str, dict[str, Any]] = {}
        for item in profiles:
            if not isinstance(item, dict) or not str(item.get("key") or "").strip():
                raise RuntimeError("every application profile requires a key")
            key = str(item["key"]).strip()
            if key in self._profiles:
                raise RuntimeError(f"duplicate application profile: {key}")
            self._profiles[key] = item

    def list(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profiles": [self._profiles[key] for key in sorted(self._profiles)],
        }

    def require(self, key: str) -> dict[str, Any]:
        profile = self._profiles.get(key)
        if profile is None:
            raise DomainError(
                code="APPLICATION_PROFILE_NOT_FOUND",
                message=f"application profile is not registered: {key}",
                status_code=422,
                details={"registered_profiles": sorted(self._profiles)},
            )
        return profile
