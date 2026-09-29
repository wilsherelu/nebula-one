"""Server-side purpose derivation: the template, rules and method content a calculation is bound to.

These are unit tests over a real SQLite session, not an engine acceptance run: they prove the
runtime refuses to derive from anything it has not verified, and that the recorded basis is exact
enough to replay a frozen answer and too exact to replay a tampered one.
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from nebula_one.config import Settings
from nebula_one.database import Database
from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.model_processing_contract import (
    load_bundled_model_processing_rules,
    load_model_processing_rules_by_reference,
    load_model_processing_rules_for_template,
)
from nebula_one.models import Application, SystemModel, SystemRevision, new_id
from nebula_one.restored_dependencies import load_restored_method_packages
from nebula_one.runtime_models import MethodPackage
from nebula_one.services.model_processing_runtime import (
    DERIVATION_BASIS_SCHEMA_VERSION,
    _resolve_rules,
    flow_selection_of,
    resolve_purpose_derivation,
    template_identity,
)
from test_steel_model_processing_assets import (
    _graph,
    _method_package,
    _saved_associations,
    _template_identity,
    _template_profile,
)

DEMAND = [
    {
        "process_uuid": "ea66dbd3-03e1-5ff8-a1d0-9662604392c0",
        "amount": 1000.0,
        "unit": "kg",
    }
]


def _profile_identity() -> dict[str, str]:
    profile, digest, _ = _template_profile()
    return {
        "id": profile["id"],
        "version": profile["version"],
        "content_sha256": digest,
    }


def test_user_supply_rule_is_explicit_and_old_secondary_review_stays_replayable():
    old = load_bundled_model_processing_rules("steel-bf-bof-secondary-co2.json")
    new = load_bundled_model_processing_rules("steel-bf-bof-secondary-co2-user-supply.json")
    graph_identity = new.reviewed_returned_graph["accepted_graph_identity_sha256"]
    template = new.applicable_template.model_dump()
    old_ref = {key: old.reference()[key] for key in ("package_id", "version", "content_sha256")}
    new_ref = {key: new.reference()[key] for key in ("package_id", "version", "content_sha256")}
    assert _resolve_rules(template, old_ref, graph_identity).purpose("cbam").background_disposition.mode == "unlink_all_background_links"
    selected = _resolve_rules(template, new_ref, graph_identity)
    assert selected.version == "1.0.3"
    assert selected.purpose("cbam").background_disposition.retained_consumer_exchange_ids == ["ore-sintering::grid-electricity-in"]
    with pytest.raises(DomainError) as error:
        _resolve_rules(template, {**new_ref, "content_sha256": "f" * 64}, graph_identity)
    assert error.value.code == "MODEL_PROCESSING_RULES_VERSION_UNAVAILABLE"


@pytest.fixture()
def steel_project(tmp_path):
    """One stored steel model, its template binding and the template's effective method package."""
    engine = Database(
        Settings(database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}")
    )
    engine.create_schema()
    graph = _graph()
    package = _method_package()
    background, mapped = _saved_associations(graph)
    context = {"seed_template": {"profile": _profile_identity()}}
    application_id, model_id, revision_id = new_id(), new_id(), new_id()
    with engine.session() as db:
        db.add(
            Application(
                id=application_id,
                name="Steel BF-BOF crude steel",
                application_type="standard_lca",
                context=deepcopy(context),
            )
        )
        db.flush()
        db.add(
            SystemModel(
                id=model_id,
                application_id=application_id,
                name="Steel BF-BOF crude steel",
                provider="nebula_lca",
                provider_base_url="http://engine.test",
                upstream_project_id="project-steel",
                upstream_version="1",
                graph_sha256=canonical_json_sha256(graph),
                graph_snapshot=deepcopy(graph),
                upstream_receipt={},
            )
        )
        db.flush()
        db.add(
            SystemRevision(
                id=revision_id,
                system_model_id=model_id,
                revision_number=1,
                label="template",
                revision_kind="base",
                graph_sha256=canonical_json_sha256(graph),
                content_sha256=canonical_json_sha256(graph),
                graph_snapshot=deepcopy(graph),
                application_context=deepcopy(context),
                status="draft",
            )
        )
        db.add(
            MethodPackage(
                package_id=package["package_id"],
                version=package["version"],
                package_kind=package["package_kind"],
                jurisdiction=package.get("jurisdiction"),
                manifest=deepcopy(package["manifest"]),
                content_sha256=package["content_sha256"],
                status="registered",
            )
        )
        db.commit()
        yield SimpleNamespace(
            db=db,
            application=db.get(Application, application_id),
            revision=db.get(SystemRevision, revision_id),
            graph=graph,
            background=background,
            mapped=mapped,
            package=package,
            identity=_profile_identity(),
        )
    engine.dispose()


def _resolve(project, purpose="cbam", **overrides):
    kwargs = {
        "revision": project.revision,
        "application": project.application,
        "purpose": purpose,
        "demand": deepcopy(DEMAND),
        "background_process_pins": deepcopy(project.background),
        "mapped_background_process_pins": deepcopy(project.mapped),
    }
    kwargs.update(overrides)
    return resolve_purpose_derivation(project.db, **kwargs)


# ---- the template binding is read, never accepted ---------------------------


def test_the_template_identity_comes_from_the_revision_it_was_imported_with(steel_project):
    assert template_identity(steel_project.revision, steel_project.application) == (
        steel_project.identity
    )


def test_a_revision_without_a_template_binding_refuses(steel_project):
    steel_project.revision.application_context = {}
    steel_project.application.context = {}
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project)
    assert excinfo.value.code == "MODEL_PROCESSING_TEMPLATE_UNBOUND"
    assert excinfo.value.status_code == 409


def test_a_revision_imported_from_another_template_version_refuses(steel_project):
    steel_project.revision.application_context["seed_template"]["profile"]["version"] = "9.9.9"
    steel_project.application.context["seed_template"]["profile"]["version"] = "9.9.9"
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project)
    assert excinfo.value.code == "MODEL_PROCESSING_TEMPLATE_MISMATCH"
    assert excinfo.value.status_code == 409
    assert excinfo.value.details["mismatches"] == {
        "version": {"template": "9.9.9", "rules": steel_project.identity["version"]}
    }


def test_a_revised_template_content_the_rules_were_never_reviewed_against_refuses(steel_project):
    steel_project.revision.application_context["seed_template"]["profile"][
        "content_sha256"
    ] = "f" * 64
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project)
    assert excinfo.value.code == "MODEL_PROCESSING_TEMPLATE_MISMATCH"
    assert list(excinfo.value.details["mismatches"]) == ["content_sha256"]


# ---- a project keeps the rules reviewed for the template revision it came from ----

# The archived package is this repository's record of the template content an earlier review was
# made against; a project imported from that template revision carries exactly that identity.
SUPERSEDED_RULES = load_bundled_model_processing_rules("steel-bf-bof-1.0.0.json")
SUPERSEDED_IDENTITY = SUPERSEDED_RULES.applicable_template.model_dump()


def _rebind_to_old_template(project):
    for container in (project.revision.application_context, project.application.context):
        container["seed_template"]["profile"] = deepcopy(SUPERSEDED_IDENTITY)
    assert project.identity != SUPERSEDED_IDENTITY


def test_a_project_on_the_older_template_revision_still_derives(steel_project):
    """A newer review must not take an existing project offline.

    Resolving by template id alone handed this run rules 1.0.1, whose electricity membership was
    reviewed against a later template content, and the calculation died on its own binding check.
    """
    _rebind_to_old_template(steel_project)

    derivation = _resolve(steel_project, purpose="lca")
    assert derivation.basis["template"] == SUPERSEDED_IDENTITY
    assert derivation.basis["model_processing_rules"] == {
        key: SUPERSEDED_RULES.reference()[key]
        for key in ("package_id", "version", "content_sha256")
    }
    assert derivation.basis["model_processing_rules"]["version"] == "1.0.0"
    assert derivation.derived.rules_reference["version"] == "1.0.0"
    # Being allowed to compute again does not migrate the project: its stored model is untouched.
    assert derivation.derived.source_graph_sha256 == canonical_json_sha256(steel_project.graph)


def test_the_older_project_records_its_own_basis_identity_not_the_newest_one(steel_project):
    """Two projects from two template revisions derive under two different, exact bases."""
    current = _resolve(steel_project, purpose="lca")
    assert current.basis["template"] == _template_identity()
    _rebind_to_old_template(steel_project)
    superseded = _resolve(steel_project, purpose="lca")

    assert superseded.basis["template"] == SUPERSEDED_IDENTITY
    assert current.basis["model_processing_rules"] != superseded.basis["model_processing_rules"]
    assert current.basis_sha256 != superseded.basis_sha256


def test_an_older_project_refuses_cbam_for_its_missing_reviewed_package_not_the_template(
    steel_project,
):
    """The residual gap is the archived method package, and it says so instead of blaming the model.

    Rules 1.0.0 cite CBAM package 1.1.0, which this installation never registered; the run refuses
    with that identity rather than with a template mismatch, so the missing asset stays actionable.
    """
    _rebind_to_old_template(steel_project)
    with pytest.raises(DomainError) as refused:
        _resolve(steel_project, purpose="cbam")
    assert refused.value.code == "METHOD_PACKAGE_NOT_FOUND"
    assert refused.value.message.endswith("cbam.eu.iron-steel.bf-bof-direct-trial@1.1.0")


def test_the_older_project_derives_cbam_once_the_archived_package_is_registered(steel_project):
    """Registering the restored content closes the gap: the old project gets its own boundary back.

    The derivation must use the package the rules pin, not the one the current template ships, so the
    process boundary, the unlink evidence and the emission set all come out of the archived content.
    """
    (restored,) = load_restored_method_packages()
    assert restored.version == "1.1.0"
    _rebind_to_old_template(steel_project)

    steel_project.db.add(
        MethodPackage(
            package_id=restored.package_id,
            version=restored.version,
            package_kind=restored.package_kind,
            jurisdiction=restored.jurisdiction,
            manifest=deepcopy(restored.payload["manifest"]),
            content_sha256=restored.content_sha256,
            status="registered",
        )
    )
    steel_project.db.commit()

    derivation = _resolve(steel_project, purpose="cbam")
    assert derivation.basis["model_processing_rules"]["version"] == "1.0.0"
    assert derivation.basis["method_packages"] == [
        {
            "package_id": restored.package_id,
            "version": restored.version,
            "content_sha256": restored.content_sha256,
        }
    ]
    # the archived package's own boundary, and no other version's
    assert {node["process_uuid"] for node in derivation.derived.graph["nodes"]} == set(
        restored.payload["manifest"]["boundary_schema"][
            "production_process_boundary"
        ]["in_boundary_process_uuids"]
    )
    assert derivation.derived.background_process_pins == []
    assert derivation.derived.mapped_background_process_pins == []
    # this package pre-limits the emission set, so no exchange selection is recorded for it
    assert flow_selection_of(derivation.derived) is None
    # registering the archived content leaves the current project's own resolution untouched
    assert steel_project.package["version"] != restored.version


# ---- the cited method package is read through the verified path -------------


def test_the_effective_method_content_is_read_from_the_stored_package(steel_project):
    derivation = _resolve(steel_project)
    assert derivation.basis["method_packages"] == [
        {
            key: steel_project.package[key]
            for key in ("package_id", "version", "content_sha256")
        }
    ]


def test_a_stored_method_package_that_is_not_the_reviewed_content_refuses(steel_project):
    manifest = deepcopy(steel_project.package["manifest"])
    manifest["boundary_schema"]["annex_ii_direct_only"] = False
    steel_project.db.query(MethodPackage).delete()
    steel_project.db.add(
        MethodPackage(
            package_id=steel_project.package["package_id"],
            version=steel_project.package["version"],
            package_kind=steel_project.package["package_kind"],
            manifest=manifest,
            content_sha256="e" * 64,
            status="registered",
        )
    )
    steel_project.db.commit()
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project)
    assert excinfo.value.code == "MODEL_PROCESSING_METHOD_PACKAGE_MISMATCH"
    assert excinfo.value.status_code == 409
    assert excinfo.value.details["expected_content_sha256"] == (
        steel_project.package["content_sha256"]
    )


def test_a_method_package_that_was_never_registered_refuses(steel_project):
    steel_project.db.query(MethodPackage).delete()
    steel_project.db.commit()
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project)
    assert excinfo.value.code == "METHOD_PACKAGE_NOT_FOUND"
    assert excinfo.value.status_code == 404


def test_a_purpose_the_rules_do_not_declare_refuses(steel_project):
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project, purpose="pcf")
    assert excinfo.value.code == "MODEL_PROCESSING_PURPOSE_UNDECLARED"


# ---- both purposes derive from one stored model without crossing ------------


def test_both_purposes_derive_from_one_stored_model_and_record_separate_bases(steel_project):
    lca = _resolve(steel_project, purpose="lca")
    cbam = _resolve(steel_project, purpose="cbam")
    assert lca.basis["source_graph_sha256"] == cbam.basis["source_graph_sha256"] == (
        canonical_json_sha256(steel_project.graph)
    )
    assert lca.basis_sha256 != cbam.basis_sha256
    assert lca.basis["purpose"] == "lca" and cbam.basis["purpose"] == "cbam"
    assert cbam.basis["effective_background_process_pins"] == []
    assert cbam.basis["effective_mapped_background_process_pins"] == []
    assert len(lca.basis["effective_background_process_pins"]) == 1
    assert len(lca.basis["effective_mapped_background_process_pins"]) == 1
    assert cbam.basis["method_packages"] and lca.basis["method_packages"] == []


def test_the_basis_records_the_sent_demand_and_the_source_model_separately(steel_project):
    derivation = _resolve(steel_project)
    assert derivation.basis["demand"] == DEMAND
    assert derivation.basis["template"] == steel_project.identity
    rules = load_model_processing_rules_for_template(steel_project.identity)
    assert derivation.basis["model_processing_rules"] == {
        key: rules.reference()[key] for key in ("package_id", "version", "content_sha256")
    }
    assert derivation.basis["schema_version"] == DERIVATION_BASIS_SCHEMA_VERSION
    assert derivation.basis["derived_graph_sha256"] == (
        derivation.derived.derived_graph_sha256
    )


def test_the_basis_is_a_deterministic_function_of_the_verified_inputs(steel_project):
    first = _resolve(steel_project)
    second = _resolve(steel_project)
    assert first.basis == second.basis
    assert first.basis_sha256 == second.basis_sha256 == canonical_json_sha256(first.basis)


def test_the_method_selection_travels_in_the_basis_as_sent(steel_project):
    without = _resolve(steel_project)
    with_methods = _resolve(steel_project, lcia_methods=["EF v3.1", "CBAM direct"])
    assert without.basis["lcia_methods"] is None
    assert with_methods.basis["lcia_methods"] == ["CBAM direct", "EF v3.1"]
    assert with_methods.basis_sha256 != without.basis_sha256


# ---- replay is by exact saved identity --------------------------------------


def test_replaying_the_saved_basis_reproduces_the_same_derivation(steel_project):
    saved = _resolve(steel_project)
    pinned = deepcopy(saved.basis)
    pinned["basis_sha256"] = saved.basis_sha256
    replayed = _resolve(steel_project, pinned_basis=pinned)
    assert replayed.basis == saved.basis
    assert replayed.basis_sha256 == saved.basis_sha256


def test_a_saved_basis_whose_own_hash_does_not_match_its_content_refuses(steel_project):
    saved = _resolve(steel_project)
    pinned = deepcopy(saved.basis)
    pinned["basis_sha256"] = "0" * 64
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project, pinned_basis=pinned)
    assert excinfo.value.code == "MODEL_PROCESSING_BASIS_DRIFT"
    assert excinfo.value.status_code == 409
    assert excinfo.value.details["expected_basis_sha256"] == "0" * 64
    assert excinfo.value.details["actual_basis_sha256"] == saved.basis_sha256


def test_a_saved_basis_claiming_another_rule_version_refuses_instead_of_re_deriving(steel_project):
    saved = _resolve(steel_project)
    pinned = deepcopy(saved.basis)
    pinned["model_processing_rules"]["version"] = "0.0.1"
    pinned["basis_sha256"] = canonical_json_sha256(
        {key: value for key, value in pinned.items() if key != "basis_sha256"}
    )
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project, pinned_basis=pinned)
    assert excinfo.value.code == "MODEL_PROCESSING_RULES_VERSION_UNAVAILABLE"
    assert excinfo.value.details["requested"]["version"] == "0.0.1"
    assert saved.basis["model_processing_rules"] in excinfo.value.details["available"]
    same_package = [row for row in excinfo.value.details["available"]
                    if row["package_id"] == saved.basis["model_processing_rules"]["package_id"]]
    assert sorted(row["version"] for row in same_package) == ["1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4"]


def test_a_saved_basis_that_no_longer_matches_the_stored_model_refuses(steel_project):
    saved = _resolve(steel_project)
    pinned = deepcopy(saved.basis)
    pinned["demand"] = [dict(DEMAND[0], amount=2000.0)]
    pinned["basis_sha256"] = canonical_json_sha256(
        {key: value for key, value in pinned.items() if key != "basis_sha256"}
    )
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project, pinned_basis=pinned)
    assert excinfo.value.code == "MODEL_PROCESSING_BASIS_DRIFT"


def test_a_saved_basis_for_another_purpose_refuses(steel_project):
    saved = _resolve(steel_project, purpose="lca")
    pinned = deepcopy(saved.basis)
    pinned["basis_sha256"] = saved.basis_sha256
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project, purpose="cbam", pinned_basis=pinned)
    assert excinfo.value.code == "MODEL_PROCESSING_BASIS_MISMATCH"
    assert excinfo.value.status_code == 409
    assert excinfo.value.details["expected_purpose"] == "lca"


def test_a_saved_basis_from_another_template_refuses(steel_project):
    saved = _resolve(steel_project)
    pinned = deepcopy(saved.basis)
    pinned["template"] = dict(saved.basis["template"], version="2.0.0")
    pinned["basis_sha256"] = saved.basis_sha256
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project, pinned_basis=pinned)
    assert excinfo.value.code == "MODEL_PROCESSING_BASIS_MISMATCH"
    assert excinfo.value.details["actual_template"] == steel_project.identity


@pytest.mark.parametrize(
    "pinned,code",
    [
        ({"schema_version": "other.v1"}, "MODEL_PROCESSING_BASIS_UNSUPPORTED"),
        (
            {
                "schema_version": DERIVATION_BASIS_SCHEMA_VERSION,
                "model_processing_rules": None,
            },
            "MODEL_PROCESSING_RULES_IDENTITY_INCOMPLETE",
        ),
    ],
)
def test_a_saved_basis_that_does_not_name_its_rules_refuses(steel_project, pinned, code):
    with pytest.raises(DomainError) as excinfo:
        _resolve(steel_project, pinned_basis=pinned)
    assert excinfo.value.code == code


# ---- the by-reference loader ------------------------------------------------


def test_the_exact_rule_identity_loads_and_anything_else_lists_what_exists():
    rules = load_model_processing_rules_for_template(_profile_identity())
    reference = {
        key: rules.reference()[key] for key in ("package_id", "version", "content_sha256")
    }
    exact = load_model_processing_rules_by_reference(**reference)
    assert exact.reference() == rules.reference()
    for field, value in (
        ("package_id", "other.model-processing"),
        ("version", "0.0.1"),
        ("content_sha256", "1" * 64),
    ):
        with pytest.raises(DomainError) as excinfo:
            load_model_processing_rules_by_reference(**dict(reference, **{field: value}))
        assert excinfo.value.code == "MODEL_PROCESSING_RULES_VERSION_UNAVAILABLE"
        assert excinfo.value.details["requested"] == dict(reference, **{field: value})
        assert reference in excinfo.value.details["available"]
