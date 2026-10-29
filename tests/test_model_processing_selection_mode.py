"""The selection strategy that keeps a variant's rule package out of the official auto-resolver.

An `explicit_only` model-processing package may be bound by an exact reference or offered to a user
variant, but it must never enter the automatic template resolver: publishing one must not change what
the ~15 unpinned official steel applications resolve to, must not silently break a real automatic
ambiguity, and must not be picked for a solve that did not name it. Old packages carry no strategy and
stay `automatic`, with their published content hash unchanged by the new field.
"""
from __future__ import annotations

import json
from copy import deepcopy
from importlib.resources import files

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.model_processing_contract import (
    ModelProcessingRules,
    list_model_processing_rules_for_template,
    load_model_processing_rules_by_reference,
    load_model_processing_rules_for_template,
)

OFFICIAL = "steel-bf-bof-model-processing-1.0.11.json"  # automatic plain, template revision 1.1.4
SELECTOR = "steel-bf-bof-model-processing-1.0.9.json"   # reviewed selector, template revision 1.1.4
OFFICIAL_VERSION = "1.0.11"


def _resource(name: str):
    return files("nebula_one").joinpath("resources/model_processing").joinpath(name)


def _payload(name: str) -> dict:
    return json.loads(_resource(name).read_text(encoding="utf-8"))


def _identity(name: str) -> dict:
    return dict(_payload(name)["content"]["applicable_template"])


def _republish(payload: dict) -> dict:
    payload["content_sha256"] = canonical_json_sha256(payload["content"])
    return payload


def _with_mode(name: str, mode: str, *, version: str, package_id: str | None = None) -> dict:
    payload = deepcopy(_payload(name))
    payload["version"] = version
    if package_id is not None:
        payload["package_id"] = package_id
    payload["content"]["selection_mode"] = mode
    return _republish(payload)


def _write(tmp_path, name: str, payload: dict) -> None:
    (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")


def test_existing_packages_default_to_automatic_and_keep_their_hash():
    """Adding the field must not rewrite old bytes or re-pin old hashes."""
    for name in (OFFICIAL, SELECTOR, "steel-bf-bof.json", "steel-bf-bof-1.0.0.json"):
        raw = _payload(name)
        assert "selection_mode" not in raw["content"], f"{name} content gained the field"
        assert canonical_json_sha256(raw["content"]) == raw["content_sha256"]
        rules = load_model_processing_rules_by_reference(
            raw["package_id"], raw["version"], raw["content_sha256"])
        assert rules.selection_mode == "automatic"


def test_explicit_only_package_is_invisible_to_auto_but_official_still_resolves(tmp_path):
    official = deepcopy(_payload(OFFICIAL))
    _write(tmp_path, OFFICIAL, official)
    _write(tmp_path, "variant.json", _with_mode(OFFICIAL, "explicit_only", version="1.0.12"))

    found = load_model_processing_rules_for_template(_identity(OFFICIAL), search_paths=[tmp_path])
    assert found.version == OFFICIAL_VERSION  # the explicit package never hijacks the official solve


def test_explicit_package_never_resolves_a_real_auto_ambiguity(tmp_path):
    first = deepcopy(_payload(OFFICIAL))
    second = deepcopy(_payload(OFFICIAL))
    second["package_id"] = "second-steel.model-processing"
    _write(tmp_path, OFFICIAL, first)
    _write(tmp_path, "second.json", _republish(second))
    _write(tmp_path, "variant.json", _with_mode(OFFICIAL, "explicit_only", version="1.0.12"))

    with pytest.raises(DomainError) as caught:
        load_model_processing_rules_for_template(_identity(OFFICIAL), search_paths=[tmp_path])
    assert caught.value.code == "MODEL_PROCESSING_PACKAGE_AMBIGUOUS"
    # Only the two automatic packages are in conflict; the explicit one is not a candidate to untie it.
    assert sorted(caught.value.details["packages"]) == [
        "second-steel.model-processing@1.0.11",
        "steel-bf-bof.model-processing@1.0.11",
    ]


def test_only_explicit_package_for_template_leaves_the_auto_resolver_with_none(tmp_path):
    _write(tmp_path, "variant.json", _with_mode(OFFICIAL, "explicit_only", version="1.0.12"))
    with pytest.raises(DomainError) as caught:
        load_model_processing_rules_for_template(_identity(OFFICIAL), search_paths=[tmp_path])
    assert caught.value.code == "MODEL_PROCESSING_PACKAGE_MISSING"


def test_explicit_only_is_loadable_by_exact_reference(tmp_path):
    variant = _with_mode(OFFICIAL, "explicit_only", version="1.0.12")
    _write(tmp_path, "variant.json", variant)
    loaded = load_model_processing_rules_by_reference(
        variant["package_id"], "1.0.12", variant["content_sha256"], search_paths=[tmp_path])
    assert loaded.selection_mode == "explicit_only"
    assert loaded.applicable_template.model_dump() == _identity(OFFICIAL)


def test_wrong_hash_or_reference_of_explicit_package_still_refused(tmp_path):
    variant = _with_mode(OFFICIAL, "explicit_only", version="1.0.12")
    _write(tmp_path, "variant.json", variant)
    with pytest.raises(DomainError) as caught:
        load_model_processing_rules_by_reference(
            variant["package_id"], "1.0.12", "0" * 64, search_paths=[tmp_path])
    assert caught.value.code == "MODEL_PROCESSING_RULES_VERSION_UNAVAILABLE"


def test_strategy_is_generic_over_a_non_steel_template(tmp_path):
    synthetic = deepcopy(_payload(OFFICIAL))
    synthetic["package_id"] = "widget.model-processing"
    synthetic["version"] = "2.0.0"
    synthetic["content"]["applicable_template"] = {
        "id": "widget-inventory", "version": "2.0.0", "content_sha256": "a" * 64}
    _write(tmp_path, "widget-auto.json", _republish(synthetic))
    explicit = deepcopy(synthetic)
    explicit["version"] = "2.0.1"
    explicit["content"]["selection_mode"] = "explicit_only"
    _write(tmp_path, "widget-explicit.json", _republish(explicit))

    widget_identity = synthetic["content"]["applicable_template"]
    auto = load_model_processing_rules_for_template(widget_identity, search_paths=[tmp_path])
    assert (auto.package_id, auto.version, auto.selection_mode) == ("widget.model-processing", "2.0.0", "automatic")


def test_list_offers_explicit_package_for_variant_binding(tmp_path):
    _write(tmp_path, OFFICIAL, deepcopy(_payload(OFFICIAL)))
    variant = _with_mode(OFFICIAL, "explicit_only", version="1.0.12")
    _write(tmp_path, "variant.json", variant)

    listed = list_model_processing_rules_for_template(
        _identity(OFFICIAL), graph_identity_sha256="0" * 64, graph=None, search_paths=[tmp_path])
    versions = {item.version for item in listed}
    assert OFFICIAL_VERSION in versions and "1.0.12" in versions  # both are explicitly bindable


def test_list_does_not_offer_a_selector_package_it_cannot_verify(tmp_path):
    """A selector package must not be listed merely because a graph hash was supplied.

    Without the graph to evaluate against, its applicability is unproven, so it is excluded; a plain
    package for the same template still lists. This closes the `graph_identity is not None` free pass.
    """
    selector = deepcopy(_payload(SELECTOR))
    _write(tmp_path, SELECTOR, selector)
    _write(tmp_path, OFFICIAL, deepcopy(_payload(OFFICIAL)))

    listed = list_model_processing_rules_for_template(
        _identity(OFFICIAL), graph_identity_sha256="b" * 64, graph=None, search_paths=[tmp_path])
    package_versions = {(item.package_id, item.version) for item in listed}
    assert (selector["package_id"], selector["version"]) not in package_versions
    assert ("steel-bf-bof.model-processing", OFFICIAL_VERSION) in package_versions
