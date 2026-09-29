"""Exact, operator-selected templates exposed by a public installation."""

import json
from pathlib import Path

from .release_resources import LANGUAGES


class ReleaseCatalog:
    def __init__(self, path: str | None):
        self.enabled = path is not None
        self.seeds: dict[tuple[str, str, str], str] = {}
        self.seed_names: dict[tuple[str, str, str], dict[str, str]] = {}
        self.casepacks: set[tuple[str, str]] = set()
        if path is None:
            return
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema_version") != "nebula_one.release_catalog.v1":
            raise ValueError("unsupported release catalog schema")
        for item in document["seed_templates"]:
            key = (item["seed_id"], item["version"], item["bundle_content_sha256"])
            if key in self.seeds:
                raise ValueError("duplicate release seed template")
            self.seeds[key] = item["title"]
            self.seed_names[key] = self._names(key, item)
        for item in document["casepacks"]:
            key = (item["id"], item["version"])
            if key in self.casepacks:
                raise ValueError("duplicate release casepack")
            self.casepacks.add(key)

    @staticmethod
    def _names(key, item) -> dict[str, str]:
        """Declared short names for the templates this installation exposes.

        A template's real name stays the canonical `title`; the map only adds the extra languages
        the operator authored, and an incomplete map is rejected rather than shown half-translated.
        """
        declared = item.get("display_name")
        if declared is None:
            return {}
        if not isinstance(declared, dict) or set(declared) != set(LANGUAGES) \
                or any(not isinstance(v, str) or not v.strip() for v in declared.values()):
            raise ValueError(f"release seed template display name is incomplete: {key[0]}")
        return {language: text.strip() for language, text in declared.items()}

    def seed_title(self, row) -> str | None:
        return self.seeds.get((row.seed_id, row.seed_version, row.bundle_content_sha256))

    def seed_display_name(self, row) -> dict[str, str]:
        return self.seed_names.get((row.seed_id, row.seed_version, row.bundle_content_sha256), {})

    def allows_seed(self, row) -> bool:
        return not self.enabled or self.seed_title(row) is not None

    def allows_casepack(self, casepack_id: str, version: str) -> bool:
        return not self.enabled or (casepack_id, version) in self.casepacks
