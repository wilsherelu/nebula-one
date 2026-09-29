"""The rule package must be self-verifying and refuse to half-load."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from importlib.resources import files

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.model_processing_contract import (
    MODEL_PROCESSING_SCHEMA_VERSION,
    ModelProcessingRules,
    load_bundled_model_processing_rules,
    load_model_processing_rules_by_reference,
    load_model_processing_rules_for_template,
)

BUNDLED = "steel-bf-bof.json"
SUPERSEDED = "steel-bf-bof-1.0.0.json"
TEMPLATE_ID = "steel-bf-bof-inventory"
UUID_LITERAL = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _resource(name: str = BUNDLED):
    return files("nebula_one").joinpath("resources/model_processing").joinpath(name)


def _payload(name: str = BUNDLED) -> dict:
    return json.loads(_resource(name).read_text(encoding="utf-8"))


def _republish(payload: dict) -> dict:
    payload["content_sha256"] = canonical_json_sha256(payload["content"])
    return payload


def test_bundled_steel_package_verifies_its_own_content_hash():
    rules = load_bundled_model_processing_rules(BUNDLED)
    assert rules.package_id == "steel-bf-bof.model-processing"
    assert rules.version == "1.0.1"
    assert rules.applicable_template.id == TEMPLATE_ID
    assert rules.purposes == ("cbam", "lca")
    assert rules.reference()["content_sha256"] == rules.content_sha256


def test_bundled_package_binds_the_template_and_method_versions():
    rules = load_bundled_model_processing_rules(BUNDLED)
    assert len(rules.applicable_template.content_sha256) == 64

    cbam = rules.purpose("cbam")
    bound = cbam.process_selection.method_package
    assert bound is not None and cbam.process_selection.process_uuids_path
    # Every declaration that justifies a lossy action cites the same reviewed package.
    assert cbam.background_disposition.evidence is not None
    assert cbam.background_disposition.evidence.method_package == bound
    assert cbam.elementary_flows.evidence is not None
    assert cbam.elementary_flows.evidence.method_package == bound
    # The rule file binds identities; it never copies the process or emission lists it points at.
    assert not UUID_LITERAL.search(_resource().read_text(encoding="utf-8"))


def test_lca_purpose_retains_the_model_without_citing_evidence():
    lca = load_bundled_model_processing_rules(BUNDLED).purpose("lca")
    assert lca.process_selection.mode == "all_model_processes"
    assert lca.background_disposition.mode == "retain_saved_pins"
    assert lca.background_disposition.evidence is None
    assert lca.cross_boundary_connections.mode == "keep_internal_edges"


def test_tampered_content_is_refused():
    payload = _payload()
    payload["content"]["purposes"]["cbam"]["background_disposition"]["mode"] = "retain_saved_pins"
    with pytest.raises(DomainError) as caught:
        ModelProcessingRules(payload, "tampered.json")
    assert caught.value.code == "MODEL_PROCESSING_PACKAGE_HASH_MISMATCH"


def test_changed_hash_without_changed_content_is_refused():
    payload = _payload()
    payload["content_sha256"] = "0" * 64
    with pytest.raises(DomainError) as caught:
        ModelProcessingRules(payload, "forged.json")
    assert caught.value.code == "MODEL_PROCESSING_PACKAGE_HASH_MISMATCH"


def test_unsupported_schema_version_is_refused():
    payload = _payload()
    payload["schema_version"] = "nebula_one.model-processing-rules.v99"
    payload = _republish(payload)
    with pytest.raises(DomainError) as caught:
        ModelProcessingRules(payload, "future.json")
    assert caught.value.code == "MODEL_PROCESSING_PACKAGE_SCHEMA_UNSUPPORTED"


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda purpose: purpose.__setitem__(
                "background_disposition", {"mode": "unlink_all_background_links"}
            ),
            "must cite the method package declaration",
        ),
        (
            lambda purpose: purpose.__setitem__(
                "background_disposition",
                {
                    "mode": "retain_saved_pins",
                    "evidence": deepcopy(
                        _payload()["content"]["purposes"]["cbam"]["background_disposition"]["evidence"]
                    ),
                },
            ),
            "must not cite method evidence",
        ),
        (
            lambda purpose: purpose.__setitem__(
                "elementary_flows", {"mode": "template_prelimited"}
            ),
            "must cite that package and the manifest path",
        ),
        (
            lambda purpose: purpose.__setitem__(
                "elementary_flows",
                {
                    "mode": "explicit_flow_rules",
                    "evidence": deepcopy(
                        _payload()["content"]["purposes"]["cbam"]["elementary_flows"]["evidence"]
                    ),
                    "rule_refs": ["test.flow-rules@1.0.0"],
                },
            ),
            "Extra inputs are not permitted",
        ),
        (
            lambda purpose: purpose["process_selection"].__setitem__(
                "process_uuids_path", None
            ),
            "must name the package and the manifest path",
        ),
        (
            lambda purpose: purpose.__setitem__(
                "cross_boundary_connections",
                {
                    "mode": "keep_internal_edges",
                    "boundary_exchanges": [
                        {
                            "exchange_id": "a::b",
                            "disposition": "keep_as_boundary_input",
                            "amount_source": "consumer_port_amount",
                            "clause": "ST-00",
                        }
                    ],
                },
            ),
            "must not declare boundary exchanges",
        ),
    ],
)
def test_a_lossy_declaration_without_justification_never_loads(mutate, expected):
    payload = _payload()
    purpose = payload["content"]["purposes"]["cbam"]
    mutate(purpose)
    payload = _republish(payload)
    with pytest.raises(DomainError) as caught:
        ModelProcessingRules(payload, "unjustified.json")
    assert caught.value.code == "MODEL_PROCESSING_PACKAGE_INVALID"
    assert expected in caught.value.message


def test_duplicate_boundary_exchange_declarations_are_refused():
    payload = _payload()
    declaration = {
        "exchange_id": "continuous-casting::grid-electricity-in",
        "disposition": "keep_as_boundary_input",
        "amount_source": "consumer_port_amount",
        "clause": "ST-12",
    }
    payload["content"]["purposes"]["cbam"]["cross_boundary_connections"] = {
        "mode": "reject_undeclared",
        "boundary_exchanges": [declaration, deepcopy(declaration)],
    }
    payload = _republish(payload)
    with pytest.raises(DomainError) as caught:
        ModelProcessingRules(payload, "duplicated.json")
    assert caught.value.code == "MODEL_PROCESSING_PACKAGE_INVALID"


def test_unknown_purpose_is_refused_rather_than_defaulted():
    rules = load_bundled_model_processing_rules(BUNDLED)
    with pytest.raises(DomainError) as caught:
        rules.purpose("pcf")
    assert caught.value.code == "MODEL_PROCESSING_PURPOSE_UNDECLARED"
    assert set(caught.value.details["declared"]) == {"cbam", "lca"}


def _identity(name: str = BUNDLED) -> dict:
    """The exact template identity a published rule package was reviewed against."""
    return dict(_payload(name)["content"]["applicable_template"])


def test_template_lookup_requires_exactly_one_package(tmp_path):
    (tmp_path / BUNDLED).write_text(_resource().read_text(encoding="utf-8"), encoding="utf-8")

    found = load_model_processing_rules_for_template(_identity(), search_paths=[tmp_path])
    assert found.package_id == "steel-bf-bof.model-processing"

    with pytest.raises(DomainError) as missing:
        load_model_processing_rules_for_template(
            {**_identity(), "id": "other-template"}, search_paths=[tmp_path])
    assert missing.value.code == "MODEL_PROCESSING_PACKAGE_MISSING"

    other = json.loads(_resource().read_text(encoding="utf-8"))
    other["package_id"] = "second-steel.model-processing"
    other = _republish(other)
    (tmp_path / "second.json").write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(DomainError) as ambiguous:
        load_model_processing_rules_for_template(_identity(), search_paths=[tmp_path])
    assert ambiguous.value.code == "MODEL_PROCESSING_PACKAGE_AMBIGUOUS"
    assert sorted(ambiguous.value.details["packages"]) == [
        "second-steel.model-processing@1.0.1",
        "steel-bf-bof.model-processing@1.0.1",
    ]


def test_a_newer_version_over_the_same_template_identity_does_not_break_the_tie(tmp_path):
    """Publishing a competing package must not let version order pick what a run means.

    Two packages that both claim this exact template identity, one of them newer, are a review
    conflict; silently preferring the higher version would reinterpret a live project's model under
    rules nobody confirmed for it.
    """
    (tmp_path / BUNDLED).write_text(_resource().read_text(encoding="utf-8"), encoding="utf-8")
    competing = json.loads(_resource().read_text(encoding="utf-8"))
    competing["package_id"] = "second-steel.model-processing"
    competing["version"] = "9.9.9"
    (tmp_path / "second.json").write_text(json.dumps(_republish(competing)), encoding="utf-8")

    with pytest.raises(DomainError) as ambiguous:
        load_model_processing_rules_for_template(_identity(), search_paths=[tmp_path])
    assert ambiguous.value.code == "MODEL_PROCESSING_PACKAGE_AMBIGUOUS"
    assert sorted(ambiguous.value.details["packages"]) == [
        "second-steel.model-processing@9.9.9",
        "steel-bf-bof.model-processing@1.0.1",
    ]


def test_a_project_from_an_older_template_revision_gets_the_rules_reviewed_for_it():
    """The newest package is not the answer: each template revision gets its own reviewed rules."""
    superseded, current = _identity(SUPERSEDED), _identity(BUNDLED)
    assert (superseded["version"], current["version"]) == ("1.1.1", "1.1.2")

    old_project = load_model_processing_rules_for_template(superseded)
    new_project = load_model_processing_rules_for_template(current)
    assert (old_project.version, new_project.version) == ("1.0.0", "1.0.1")
    assert old_project.applicable_template.model_dump() == superseded
    assert new_project.applicable_template.model_dump() == current
    # Both revisions stay computable, and each still declares the same two purposes.
    assert old_project.purposes == new_project.purposes == ("cbam", "lca")


def test_a_template_content_no_package_was_reviewed_against_reports_every_binding():
    with pytest.raises(DomainError) as mismatch:
        load_model_processing_rules_for_template({**_identity(), "content_sha256": "f" * 64})
    assert mismatch.value.code == "MODEL_PROCESSING_TEMPLATE_MISMATCH"
    assert mismatch.value.status_code == 409
    assert mismatch.value.details["mismatches"] == {
        "content_sha256": {"template": "f" * 64, "rules": _identity()["content_sha256"]}
    }
    assert [(item["version"], item["template"]["version"])
            for item in mismatch.value.details["reviewed_by"]] == [
            ("1.0.0", "1.1.1"), ("1.0.1", "1.1.2"), ("1.0.2", "1.1.2"),
            ("1.0.3", "1.1.2"), ("1.0.4", "1.1.2")]


def test_a_lookup_without_the_full_template_identity_is_refused(tmp_path):
    (tmp_path / BUNDLED).write_text(_resource().read_text(encoding="utf-8"), encoding="utf-8")
    for partial in (TEMPLATE_ID, {"id": TEMPLATE_ID, "version": "1.1.2"}):
        with pytest.raises(DomainError) as refused:
            load_model_processing_rules_for_template(partial, search_paths=[tmp_path])
        assert refused.value.code == "MODEL_PROCESSING_TEMPLATE_IDENTITY_INCOMPLETE"
        assert refused.value.status_code == 409


def test_a_superseded_rule_version_stays_replayable_by_its_exact_identity():
    """Publishing the next rules version must not silently change what an already frozen answer
    was derived with, so the superseded package stays on disk and loads on its own identity."""
    archived = _payload(SUPERSEDED)
    current = load_model_processing_rules_for_template(_identity())
    assert current.version == "1.0.1" and current.package_id == "steel-bf-bof.model-processing"

    old = load_model_processing_rules_by_reference(
        archived["package_id"], archived["version"], archived["content_sha256"])
    assert (old.version, old.package_id) == ("1.0.0", "steel-bf-bof.model-processing")
    assert old.applicable_template.version != current.applicable_template.version
    assert old.purposes == current.purposes
    # The superseded package pins the flow identities of its own template revision, and only that.
    assert old.applicable_template.content_sha256 != current.applicable_template.content_sha256


def test_secondary_co2_review_selects_only_its_exact_returned_graph():
    reviewed = _payload("steel-bf-bof-secondary-co2.json")
    graph_pin = reviewed["content"]["reviewed_returned_graph"]["accepted_graph_identity_sha256"]
    source_pin = reviewed["content"]["reviewed_returned_graph"]["source_graph_identity_sha256"]
    with pytest.raises(DomainError) as ambiguous:
        load_model_processing_rules_for_template(_identity(), graph_identity_sha256=graph_pin)
    assert ambiguous.value.code == "MODEL_PROCESSING_PACKAGE_AMBIGUOUS"
    selected = load_model_processing_rules_by_reference(
        reviewed["package_id"], reviewed["version"], reviewed["content_sha256"])
    assert selected.version == "1.0.2"
    assert selected.purpose("cbam").process_selection.method_package.version == "1.1.2"
    assert selected.reviewed_returned_graph["boundary_rule"]["exchange_id"] == (
        "secondary-metallurgy-and-degassing::output_da4f27")
    assert load_model_processing_rules_for_template(
        _identity(), graph_identity_sha256=source_pin).version == "1.0.1"
    assert load_model_processing_rules_for_template(
        _identity(), graph_identity_sha256="0" * 64).version == "1.0.1"


def test_unreadable_package_reports_its_path(tmp_path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(DomainError) as caught:
        load_model_processing_rules_for_template(_identity(), search_paths=[tmp_path])
    assert caught.value.code == "MODEL_PROCESSING_PACKAGE_UNREADABLE"


def test_schema_version_constant_matches_the_bundled_declaration():
    assert _payload()["schema_version"] == MODEL_PROCESSING_SCHEMA_VERSION
