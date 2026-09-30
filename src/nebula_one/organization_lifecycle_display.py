"""Exact, versioned display projection for an immutable organization method."""
from __future__ import annotations

import json
from pathlib import Path

from .errors import DomainError
from .hashing import canonical_json_sha256


PROJECTION_ROOT = Path(__file__).resolve().parent / "resources" / "organization_lifecycle_display"


def organization_lifecycle_display(method, language: str) -> dict:
    projection_path = PROJECTION_ROOT / f"steel-{method.version}-en.v1.json"
    if not projection_path.is_file():
        raise DomainError(code="ORGANIZATION_DISPLAY_SOURCE_MISMATCH",
                          message="No display projection is pinned to this exact organization method", status_code=409)
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    source = projection["method_package"]
    if (method.package_id != source["package_id"] or method.version != source["version"]
            or method.content_sha256 != source["content_sha256"]
            or method.package_kind != "organization_lifecycle_carbon"):
        raise DomainError(code="ORGANIZATION_DISPLAY_SOURCE_MISMATCH",
                          message="No display projection is pinned to this exact organization method", status_code=409)
    rules = method.manifest["classification_rules"]["other_value_chain_categories"]
    original = method.manifest["display_labels"]
    labels = projection["labels"]
    exchange_labels = {key: value for rule in rules.values()
                       for key, value in rule.get("exchange_labels", {}).items()}
    if (projection["schema_version"] != "nebula_one.organization-lifecycle-display.v1"
            or projection["language"] != "en"
            or set(labels["categories"]) != set(rules)
            or set(labels["exchanges"]) != set(exchange_labels)
            or set(labels["input_basis"]) != set(original["input_basis"])
            or set(labels["group_status"]) != set(original["group_status"])):
        raise DomainError(code="ORGANIZATION_DISPLAY_INCOMPLETE",
                          message="Display projection does not cover the exact organization method", status_code=409)
    if language == "zh":
        shown = {"input_basis": original["input_basis"], "group_status": original["group_status"],
                 "categories": {key: rule["name"] for key, rule in rules.items()},
                 "exchanges": exchange_labels}
    elif language == "en":
        shown = labels
    else:
        raise DomainError(code="ORGANIZATION_DISPLAY_LANGUAGE_INVALID",
                          message="Unsupported display language", status_code=422)
    return {"schema_version": projection["schema_version"], "version": projection["version"],
            "language": language, "method_package": source,
            "projection_sha256": canonical_json_sha256(projection), "labels": shown}
