from __future__ import annotations

from sqlalchemy import select

from nebula_one.hashing import canonical_graph_sha256


def _create_application(client) -> dict:
    response = client.post(
        "/api/v1/applications",
        json={
            "name": "Calc methods fixture",
            "application_type": "zero_carbon_park",
            "description": "calculation methods acceptance",
            "context": {"geography": "CN-SH"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _attach_inline_model(client, application_id: str, graph: dict, source_version: int = 1) -> dict:
    response = client.post(
        f"/api/v1/applications/{application_id}/system-models/inline",
        json={
            "name": "Inline model",
            "provider": "nebula_lca",
            "source_id": "casepack:petrochemical-refinery-reference",
            "source_version": source_version,
            "expected_graph_sha256": canonical_graph_sha256(graph),
            "graph": graph,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _graph_process_ids(client, revision_id: str) -> list[str]:
    response = client.get(f"/api/v1/system-revisions/{revision_id}")
    assert response.status_code == 200, response.text
    snapshot = response.json()["graph_snapshot"]
    return [node["id"] for node in snapshot.get("nodes") or []]


def _setup(client, model_graph):
    application = _create_application(client)
    system_model = _attach_inline_model(client, application["id"], model_graph)
    revision_id = system_model["upstream_receipt"]["base_revision_id"]
    return application, revision_id


def test_create_list_and_read_back_calculation_method(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]

    payload = {
        "name": "Steel direct CBAM",
        "purpose": "cbam",
        "model_revision_id": revision_id,
        "description": "user method draft",
        "rules": [
            {
                "process_instance_id": node_id,
                "direction": "emission",
                "boundary_status": "selected",
                "location_role": "onsite",
                "scope": "scope_1",
                "cbam_relevant": True,
                "classification_basis": "user",
            }
        ],
    }
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods", json=payload
    )
    assert created.status_code == 201, created.text
    body = created.json()
    method_id = body["method"]["id"]
    assert body["latest_version"] == 1
    assert len(body["versions"]) == 1
    version = body["versions"][0]
    assert version["version"] == 1
    assert version["content_sha256"]
    assert version["status"] == "draft"
    assert version["rules"][0]["process_instance_id"] == node_id
    assert version["rules"][0]["scope"] == "scope_1"

    listed = client.get(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        params={"model_revision_id": revision_id},
    )
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == method_id for item in listed.json())

    detail = client.get(f"/api/v1/calculation-methods/{method_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["method"]["name"] == "Steel direct CBAM"

    read_version = client.get(f"/api/v1/calculation-methods/{method_id}/versions/1")
    assert read_version.status_code == 200, read_version.text
    assert read_version.json()["content_sha256"] == version["content_sha256"]


def test_method_persists_across_repeated_reads(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Persisted",
            "purpose": "pcf",
            "model_revision_id": revision_id,
            "rules": [{"process_instance_id": node_id, "direction": "input"}],
        },
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]
    again = client.get(f"/api/v1/calculation-methods/{method_id}")
    assert again.json()["latest_version"] == 1
    assert again.json()["versions"][0]["rules"][0]["direction"] == "input"


def test_rejects_rule_for_process_absent_from_revision(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    rejected = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Bad process",
            "purpose": "cbam",
            "model_revision_id": revision_id,
            "rules": [{"process_instance_id": "does-not-exist", "direction": "emission"}],
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "BOUND_PROCESS_NOT_FOUND"


def test_rejects_duplicate_rule_identity(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    rule = {
        "process_instance_id": node_id,
        "exchange_id": "x1",
        "flow_uuid": "f1",
        "direction": "input",
    }
    rejected = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Duplicate rules",
            "purpose": "cbam",
            "model_revision_id": revision_id,
            "rules": [rule, dict(rule)],
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "CALCULATION_METHOD_RULE_DUPLICATE"


def test_excluded_rule_retains_scope_for_tracking(client, model_graph):
    # Inclusion and result-grouping are independent: excluding a flow keeps the Scope it carried so
    # the reader can still track its original classification. The grouping kernels bucket `excluded`
    # before any Scope, so the retained value never re-enters a total.
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Excluded keeps scope",
            "purpose": "cbam",
            "model_revision_id": revision_id,
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "excluded",
                    "scope": "scope_1",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    saved = created.json()["versions"][0]["rules"][0]
    assert saved["boundary_status"] == "excluded"
    assert saved["scope"] == "scope_1"


def test_unknown_method_version_returns_404(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "One version",
            "purpose": "cbam",
            "model_revision_id": revision_id,
            "rules": [{"process_instance_id": node_id, "direction": "input"}],
        },
    )
    method_id = created.json()["method"]["id"]
    missing = client.get(f"/api/v1/calculation-methods/{method_id}/versions/99")
    assert missing.status_code == 404, missing.text
    assert missing.json()["error"]["code"] == "CALCULATION_METHOD_VERSION_NOT_FOUND"


def _create_method(client, application, revision_id, node_id, scope="scope_1", name="Steel direct CBAM"):
    response = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": name,
            "purpose": "cbam",
            "model_revision_id": revision_id,
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "selected",
                    "location_role": "onsite",
                    "scope": scope,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_boundary(client, application) -> str:
    response = client.post(
        f"/api/v1/applications/{application['id']}/boundaries",
        json={"name": "CBAM 2026 production", "boundary_type": "cbam_production"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _cbam_rule(node_id, revision_id, boundary_ref, location="onsite", scope="scope_1"):
    return {
        "name": "Valid CBAM",
        "purpose": "cbam",
        "model_revision_id": revision_id,
        "cbam_boundary_ref": boundary_ref,
        "rules": [
            {
                "process_instance_id": node_id,
                "direction": "emission",
                "boundary_status": "selected",
                "location_role": location,
                "scope": scope,
                "cbam_relevant": True,
                "classification_basis": "user",
            }
        ],
    }


def test_validate_accepts_fully_configured_cbam_method(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    boundary_id = _create_boundary(client, application)
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json=_cbam_rule(node_id, revision_id, boundary_id),
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]

    validated = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/validate"
    )
    assert validated.status_code == 200, validated.text
    body = validated.json()
    assert body["valid"] is True
    assert body["problems"] == []
    assert body["status"] == "ready"
    assert body["validated_at"]
    assert body["content_sha256"] == created.json()["versions"][0]["content_sha256"]


def test_validate_requires_cbam_boundary_for_cbam_purpose(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    # identical rule set to the accepted case, only the boundary reference removed
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json=_cbam_rule(node_id, revision_id, None),
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]

    validated = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/validate"
    )
    assert validated.status_code == 200, validated.text
    body = validated.json()
    assert body["valid"] is False
    assert body["status"] == "draft"
    codes = {problem["code"] for problem in body["problems"]}
    assert "CALCULATION_METHOD_CBAM_BOUNDARY_REQUIRED" in codes


def test_validate_flags_scope_location_mismatch(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Mismatched scope",
            "purpose": "organization",
            "model_revision_id": revision_id,
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "selected",
                    "location_role": "onsite",
                    "scope": "scope_2",
                    "classification_basis": "user",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]

    validated = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/validate"
    )
    body = validated.json()
    assert body["valid"] is False
    mismatch = next(
        problem
        for problem in body["problems"]
        if problem["code"] == "CALCULATION_METHOD_SCOPE_LOCATION_MISMATCH"
    )
    assert mismatch["process_instance_id"] == node_id
    assert mismatch["rule_index"] == 0


def test_validate_flags_unclassified_and_missing_scope(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Incomplete organization",
            "purpose": "organization",
            "model_revision_id": revision_id,
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "selected",
                    "location_role": "onsite",
                    "scope": None,
                    "classification_basis": "unclassified",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]

    validated = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/validate"
    )
    body = validated.json()
    codes = {problem["code"] for problem in body["problems"]}
    assert "CALCULATION_METHOD_UNCLASSIFIED" in codes
    assert "CALCULATION_METHOD_MISSING_SCOPE" in codes


def test_validate_rejects_unknown_method(client, model_graph):
    missing = client.post("/api/v1/calculation-methods/nope/versions/1/validate")
    assert missing.status_code == 404, missing.text
    assert missing.json()["error"]["code"] == "CALCULATION_METHOD_NOT_FOUND"


def _queue_solve(client, application_id, revision_id, method_ref=None, demand=None):
    payload = {"demand": demand or [{"amount": 1.0, "unit": "kg", "reference_flow_uuid": "flow-product"}]}
    if method_ref is not None:
        payload["calculation_method_ref"] = method_ref
    return client.post(
        f"/api/v1/applications/{application_id}/system-revisions/{revision_id}/solve/queue",
        json=payload,
    )


def _ready_cbam_method(client, application, revision_id, node_id):
    boundary_id = _create_boundary(client, application)
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json=_cbam_rule(node_id, revision_id, boundary_id),
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]
    content_hash = created.json()["versions"][0]["content_sha256"]
    validated = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/validate"
    )
    assert validated.json()["valid"] is True, validated.text
    return method_id, content_hash


def test_solve_queue_accepts_exact_ready_method_and_persists_ref(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, content_hash = _ready_cbam_method(client, application, revision_id, node_id)

    queued = _queue_solve(
        client, application["id"], revision_id,
        {"method_id": method_id, "version": 1, "content_sha256": content_hash},
    )
    assert queued.status_code == 202, queued.text
    run = queued.json()["run"]
    assert run["parameters"]["calculation_method_ref"] == {
        "method_id": method_id, "version": 1, "content_sha256": content_hash,
    }


def test_solve_rejects_method_bound_to_another_revision(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, content_hash = _ready_cbam_method(client, application, revision_id, node_id)
    # a second revision of the same application is not the one the method is bound to
    other_model = _attach_inline_model(client, application["id"], model_graph, source_version=2)
    other_revision = other_model["upstream_receipt"]["base_revision_id"]
    assert other_revision != revision_id

    refused = _queue_solve(
        client, application["id"], other_revision,
        {"method_id": method_id, "version": 1, "content_sha256": content_hash},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "CALCULATION_METHOD_REVISION_MISMATCH"


def test_solve_accepts_exact_validated_history_version_after_a_newer_version_is_saved(client, model_graph):
    """P3-B / R2 correction: an immutable, validated history version stays runnable.

    Saving a newer version moves the head but never mutates the prior row, so a run that
    names the exact superseded version (and its hash) must still resolve - otherwise editing
    a method would silently break every already-created run that replayed the older grouping.
    """
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, content_hash = _ready_cbam_method(client, application, revision_id, node_id)
    moved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "selected",
                    "location_role": "purchased_energy",
                    "scope": "scope_2",
                    "cbam_relevant": True,
                }
            ],
            "expected_content_sha256": content_hash,
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["latest_version"] == 2

    # The exact v1 ref still resolves directly to the frozen v1 rules.
    from nebula_one.runtime_schemas import CalculationMethodRef

    container = client.app.state.container
    ref = CalculationMethodRef(method_id=method_id, version=1, content_sha256=content_hash)
    with container.database.session() as db:
        snapshot = container.provider_solves._resolve_user_calculation_method(
            db, application["id"], revision_id, "cbam", ref
        )
    assert snapshot["version"] == 1
    assert snapshot["content_sha256"] == content_hash

    accepted = _queue_solve(
        client, application["id"], revision_id,
        {"method_id": method_id, "version": 1, "content_sha256": content_hash},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["run"]["parameters"]["calculation_method_ref"] == {
        "method_id": method_id, "version": 1, "content_sha256": content_hash,
    }


def test_solve_still_rejects_a_superseded_version_that_is_not_ready(client, model_graph):
    """Dropping the head check must not weaken validation: a superseded, unvalidated row is refused.

    v1 is now both superseded (a v2 exists) and still a draft, so the ONLY reason it is refused
    is that it was never validated - proving the resolver no longer rejects on head position but
    still fails closed on status.
    """
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    body = _create_method(client, application, revision_id, node_id)
    method_id = body["method"]["id"]
    draft_hash = body["versions"][0]["content_sha256"]

    moved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={"rules": [{"process_instance_id": node_id, "direction": "emission"}], "expected_content_sha256": draft_hash},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["latest_version"] == 2

    refused = _queue_solve(
        client, application["id"], revision_id,
        {"method_id": method_id, "version": 1, "content_sha256": draft_hash},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "CALCULATION_METHOD_NOT_VALIDATED"


def test_solve_rejects_hash_mismatch_for_method_version(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, _content_hash = _ready_cbam_method(client, application, revision_id, node_id)

    refused = _queue_solve(
        client, application["id"], revision_id,
        {"method_id": method_id, "version": 1, "content_sha256": "0" * 64},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "CALCULATION_METHOD_HASH_MISMATCH"


def test_solve_rejects_unvalidated_method_version(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    boundary_id = _create_boundary(client, application)
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json=_cbam_rule(node_id, revision_id, boundary_id),
    )
    method_id = created.json()["method"]["id"]
    content_hash = created.json()["versions"][0]["content_sha256"]
    # deliberately no validate call, so the head version stays draft

    refused = _queue_solve(
        client, application["id"], revision_id,
        {"method_id": method_id, "version": 1, "content_sha256": content_hash},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "CALCULATION_METHOD_NOT_VALIDATED"


def test_resolve_snapshot_carries_identity_and_immutable_rules(client, model_graph):
    from nebula_one.runtime_schemas import CalculationMethodRef

    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, content_hash = _ready_cbam_method(client, application, revision_id, node_id)

    container = client.app.state.container
    ref = CalculationMethodRef(method_id=method_id, version=1, content_sha256=content_hash)
    with container.database.session() as db:
        snapshot = container.provider_solves._resolve_user_calculation_method(
            db, application["id"], revision_id, "cbam", ref
        )
    assert snapshot is not None
    assert snapshot["method_id"] == method_id
    assert snapshot["version"] == 1
    assert snapshot["content_sha256"] == content_hash
    assert snapshot["model_revision_id"] == revision_id
    assert snapshot["purpose"] == "cbam"
    # the rules snapshot is the exact persisted grouping, copied verbatim for provenance only
    assert snapshot["rules"][0]["process_instance_id"] == node_id
    assert snapshot["rules"][0]["scope"] == "scope_1"
    assert snapshot["validated_at"]
    # R2: the same entry compiles an immutable execution plan and freezes its hash, so a
    # recovered or replayed run reproduces the exact grouping rather than re-interpreting rules.
    assert snapshot["schema_version"] == "nebula_one.method-execution-plan.v1"
    assert snapshot["compiler_version"] == "nebula_one.method-compiler.v1"
    assert len(snapshot["execution_plan_sha256"]) == 64
    resolved = snapshot["execution_plan"]["resolved_targets"]
    assert any(item["process_instance_id"] == node_id for item in resolved)


def test_save_creates_new_immutable_version_and_reads_back(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    body = _create_method(client, application, revision_id, node_id)
    method_id = body["method"]["id"]
    v1_hash = body["versions"][0]["content_sha256"]

    saved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "selected",
                    "location_role": "purchased_energy",
                    "scope": "scope_2",
                }
            ],
            "expected_content_sha256": v1_hash,
        },
    )
    assert saved.status_code == 200, saved.text
    after = saved.json()
    assert after["latest_version"] == 2
    assert len(after["versions"]) == 2
    v2 = next(item for item in after["versions"] if item["version"] == 2)
    assert v2["rules"][0]["scope"] == "scope_2"
    assert v2["content_sha256"] != v1_hash
    # the prior version stays frozen and readable through the versioned endpoint
    v1_read = client.get(f"/api/v1/calculation-methods/{method_id}/versions/1")
    assert v1_read.json()["rules"][0]["scope"] == "scope_1"
    assert v1_read.json()["content_sha256"] == v1_hash


def test_single_inclusion_toggle_compiles_cbam_relevance_and_scope_on_one_edit(client, model_graph):
    """F3: the unified editor's one 是否计入 switch + inline Scope write both legacy fields.

    The reader marks a contribution 计入 and picks Scope 2 in a single edit and never touches a
    second ``cbam_relevant`` switch. For a CBAM-purpose method the backend makes a counted
    contribution relevant (counting a flow the regulation does not reach is the one refused
    direction) and persists the Scope unchanged, so the official read-back is consistent without
    the client syncing two flags. Narrowing that contribution back OUT keeps it CBAM-relevant —
    exclusion is a legal narrowing of a regulated emission, not a de-regulation — and keeps the
    Scope too, so re-inclusion restores the same classification.
    """
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, v1_hash, _boundary = _ready_cbam(client, application, revision_id, node_id)

    saved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "selected",
                    "location_role": "purchased_energy",
                    "scope": "scope_2",
                    # no cbam_relevant switch is sent: the single inclusion toggle drives it
                    "cbam_relevant": False,
                }
            ],
            "expected_content_sha256": v1_hash,
        },
    )
    assert saved.status_code == 200, saved.text
    v2 = next(item for item in saved.json()["versions"] if item["version"] == 2)
    rule = v2["rules"][0]
    assert rule["boundary_status"] == "selected"
    assert rule["scope"] == "scope_2"
    assert rule["cbam_relevant"] is True

    read_back = client.get(f"/api/v1/calculation-methods/{method_id}/versions/2").json()
    assert read_back["rules"][0]["cbam_relevant"] is True
    assert read_back["rules"][0]["scope"] == "scope_2"

    # excluding the same contribution through the one toggle is a narrowing: the regulated
    # emission stays CBAM-relevant (so a narrowing-only variant still engages the regulation)
    excluded = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/2",
        json={
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "excluded",
                    "location_role": "purchased_energy",
                    "scope": "scope_2",
                    "cbam_relevant": True,
                }
            ],
            "expected_content_sha256": v2["content_sha256"],
        },
    )
    assert excluded.status_code == 200, excluded.text
    v3 = next(item for item in excluded.json()["versions"] if item["version"] == 3)
    assert v3["rules"][0]["cbam_relevant"] is True
    # exclusion preserves the original classification so re-inclusion can restore it
    assert v3["rules"][0]["scope"] == "scope_2"


def _ready_cbam(client, application, revision_id, node_id):
    boundary_id = _create_boundary(client, application)
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json=_cbam_rule(node_id, revision_id, boundary_id),
    )
    method_id = created.json()["method"]["id"]
    content_hash = created.json()["versions"][0]["content_sha256"]
    validated = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate")
    assert validated.json()["valid"] is True, validated.text
    return method_id, content_hash, boundary_id


def test_queued_solve_fingerprint_covers_the_compiled_execution_plan_and_retries_are_one_run(
    client, model_graph
):
    """R6: the compiled plan + compiler version are result-affecting inputs of the accepted request.

    They must sit inside the request fingerprint (a retried identical submit is the same run, never
    a duplicate) and be exactly the hash the shared execution contract compiled, so a later method
    edit or compiler bump can never reuse a queued run's stale grouping.
    """
    from nebula_one.runtime_schemas import CalculationMethodRef

    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, v1_hash, _boundary = _ready_cbam(client, application, revision_id, node_id)
    ref = {"method_id": method_id, "version": 1, "content_sha256": v1_hash}

    first = _queue_solve(client, application["id"], revision_id, ref)
    assert first.status_code == 202, first.text
    run = first.json()["run"]
    plan_hash = run["parameters"]["calculation_execution_plan_sha256"]
    assert len(plan_hash) == 64
    assert run["parameters"]["calculation_compiler_version"] == "nebula_one.method-compiler.v1"

    # the fingerprint's plan hash is the very plan the shared contract compiled for this version.
    container = client.app.state.container
    with container.database.session() as db:
        snapshot = container.provider_solves._resolve_user_calculation_method(
            db, application["id"], revision_id, "cbam", CalculationMethodRef(**ref)
        )
    assert plan_hash == snapshot["execution_plan_sha256"]

    # duplicate submit for the identical method version is the same accepted run, not a new one.
    again = _queue_solve(client, application["id"], revision_id, ref)
    assert again.status_code == 202, again.text
    second = again.json()["run"]
    assert second["id"] == run["id"]
    assert second["request_sha256"] == run["request_sha256"]


def test_editing_method_gives_a_new_plan_and_distinct_run_while_the_v1_replay_stays_stable(
    client, model_graph
):
    """R6: queued-then-modify must not rewrite a frozen run, and a new version is never a stale hit.

    Saving v2 moves the head but leaves v1 immutable. Re-accepting the exact v1 reference after the
    edit reproduces v1's identical plan hash and request identity; v2 compiles a different plan, so
    it is a distinct accepted request and cannot land on v1's frozen answer or cached grouping.
    """
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, v1_hash, boundary_id = _ready_cbam(client, application, revision_id, node_id)

    v1 = _queue_solve(
        client, application["id"], revision_id,
        {"method_id": method_id, "version": 1, "content_sha256": v1_hash},
    )
    assert v1.status_code == 202, v1.text
    v1_run = v1.json()["run"]
    v1_plan = v1_run["parameters"]["calculation_execution_plan_sha256"]
    v1_req = v1_run["request_sha256"]

    moved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "cbam_boundary_ref": boundary_id,
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "selected",
                    "location_role": "purchased_energy",
                    "scope": "scope_2",
                    "cbam_relevant": True,
                }
            ],
            "expected_content_sha256": v1_hash,
        },
    )
    assert moved.status_code == 200, moved.text
    v2 = next(item for item in moved.json()["versions"] if item["version"] == 2)
    v2_hash = v2["content_sha256"]
    validated = client.post(f"/api/v1/calculation-methods/{method_id}/versions/2/validate")
    assert validated.json()["valid"] is True, validated.text

    v1_again = _queue_solve(
        client, application["id"], revision_id,
        {"method_id": method_id, "version": 1, "content_sha256": v1_hash},
    )
    replay = v1_again.json()["run"]
    assert replay["request_sha256"] == v1_req
    assert replay["parameters"]["calculation_execution_plan_sha256"] == v1_plan

    v2_run = _queue_solve(
        client, application["id"], revision_id,
        {"method_id": method_id, "version": 2, "content_sha256": v2_hash},
    )
    assert v2_run.status_code == 202, v2_run.text
    accepted = v2_run.json()["run"]
    assert accepted["parameters"]["calculation_execution_plan_sha256"] != v1_plan
    assert accepted["request_sha256"] != v1_req


def test_save_rejects_stale_content_hash(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    body = _create_method(client, application, revision_id, node_id)
    method_id = body["method"]["id"]
    conflict = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": [{"process_instance_id": node_id, "direction": "input"}],
            "expected_content_sha256": "0" * 64,
        },
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "CALCULATION_METHOD_CONFLICT"


def test_save_requires_latest_base_version(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    body = _create_method(client, application, revision_id, node_id)
    method_id = body["method"]["id"]
    v1_hash = body["versions"][0]["content_sha256"]
    first = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": [{"process_instance_id": node_id, "direction": "input"}],
            "expected_content_sha256": v1_hash,
        },
    )
    assert first.status_code == 200, first.text
    # version 1 is no longer the head even though its own hash still matches
    stale = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": [{"process_instance_id": node_id, "direction": "output"}],
            "expected_content_sha256": v1_hash,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "CALCULATION_METHOD_CONFLICT"
    assert stale.json()["error"]["details"]["current_version"] == 2


def test_save_rejects_rule_for_absent_process(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    body = _create_method(client, application, revision_id, node_id)
    method_id = body["method"]["id"]
    v1_hash = body["versions"][0]["content_sha256"]
    rejected = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": [{"process_instance_id": "does-not-exist", "direction": "input"}],
            "expected_content_sha256": v1_hash,
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "BOUND_PROCESS_NOT_FOUND"


def test_clone_creates_method_with_origin_kept(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    body = _create_method(client, application, revision_id, node_id)
    method_id = body["method"]["id"]
    source_hash = body["versions"][0]["content_sha256"]
    cloned = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/clone",
        json={"name": "Cloned method", "purpose": "pcf", "model_revision_id": revision_id},
    )
    assert cloned.status_code == 201, cloned.text
    after = cloned.json()
    assert after["method"]["id"] != method_id
    assert after["method"]["origin_method_id"] == method_id
    # A variant is pinned to the exact immutable source version it was copied from, not to the
    # source method's current head: a later edit on the source must not silently move the variant's
    # traceability identity.
    assert after["method"]["origin_method_version"] == 1
    assert after["method"]["origin_content_sha256"] == source_hash
    assert after["method"]["purpose"] == "pcf"
    assert after["latest_version"] == 1
    assert after["versions"][0]["rules"][0]["scope"] == "scope_1"


def test_a_validated_source_clone_restarts_as_draft_without_inheriting_validation(client, model_graph):
    """A clone never inherits its source's compliance status: it must re-validate to be runnable.

    The plan's guarantee is that a variant result cannot claim compliance by association: even when
    the source version is ``ready``, the cloned method and its v1 version come back as ``draft`` with
    no validated timestamp, so no solve can reference the variant until an operator re-runs
    validation against the variant's own rules.
    """
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    boundary_id = _create_boundary(client, application)
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json=_cbam_rule(node_id, revision_id, boundary_id),
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]
    source_hash = created.json()["versions"][0]["content_sha256"]
    validated = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["status"] == "ready"

    cloned = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/clone",
        json={"name": "Variant of a ready method", "purpose": "cbam", "model_revision_id": revision_id},
    )
    assert cloned.status_code == 201, cloned.text
    after = cloned.json()
    assert after["method"]["status"] == "draft"
    assert after["versions"][0]["status"] == "draft"
    assert after["versions"][0]["validated_at"] is None
    # The variant is still pinned to the exact source version and hash it was copied from, even
    # though the source's ready status did not carry over: provenance and compliance are separate.
    assert after["method"]["origin_method_id"] == method_id
    assert after["method"]["origin_method_version"] == 1
    assert after["method"]["origin_content_sha256"] == source_hash


def test_clone_rejects_duplicate_name_for_revision(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    body = _create_method(client, application, revision_id, node_id)
    method_id = body["method"]["id"]
    conflict = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/clone",
        json={"name": "Steel direct CBAM", "purpose": "cbam", "model_revision_id": revision_id},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "CALCULATION_METHOD_NAME_CONFLICT"


def test_repeated_identical_save_is_idempotent(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    body = _create_method(client, application, revision_id, node_id)
    method_id = body["method"]["id"]
    v1_hash = body["versions"][0]["content_sha256"]
    rules = [
        {
            "process_instance_id": node_id,
            "direction": "emission",
            "boundary_status": "selected",
            "location_role": "purchased_energy",
            "scope": "scope_2",
        }
    ]
    first = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={"rules": rules, "expected_content_sha256": v1_hash},
    )
    assert first.status_code == 200, first.text
    assert first.json()["latest_version"] == 2

    replay = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={"rules": rules, "expected_content_sha256": v1_hash},
    )
    assert replay.status_code == 200, replay.text
    # an identical re-submit is a replay, so it must not append a third version
    assert replay.json()["latest_version"] == 2
    assert len(replay.json()["versions"]) == 2
    head = next(item for item in replay.json()["versions"] if item["version"] == 2)
    assert head["content_sha256"] == first.json()["versions"][0]["content_sha256"]


# --- R2: one shared execution contract resolves, validates and compiles the plan ---


def _resolve_plan(container, application_id, revision_id, purpose, ref, require_ready=True):
    from nebula_one.services.method_execution_contract import (
        resolve_method_execution_plan,
    )

    with container.database.session() as db:
        return resolve_method_execution_plan(
            db,
            application_id=application_id,
            system_revision_id=revision_id,
            purpose=purpose,
            ref=ref,
            require_ready=require_ready,
        )


def _ref(method_id, version, content_sha256):
    return {
        "method_id": method_id,
        "version": version,
        "content_sha256": content_sha256,
    }


def test_execution_plan_replays_v1_unchanged_after_editing_v2(client, model_graph):
    """A frozen v1 plan hash is stable across a later v2 edit, and v2 compiles a different plan.

    This is the R2 replay guarantee: creating or editing v2 must not move what an accepted v1 run
    resolves to. The plan is a pure function of the version's own immutable rules, so re-resolving
    v1 after v2 exists returns the identical ``execution_plan_sha256``, while v2 (a different scope)
    freezes a different plan.
    """
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    boundary_id = _create_boundary(client, application)
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json=_cbam_rule(node_id, revision_id, boundary_id),
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]
    v1_hash = created.json()["versions"][0]["content_sha256"]
    assert client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate").json()["valid"] is True
    container = client.app.state.container

    plan_v1 = _resolve_plan(container, application["id"], revision_id, "cbam", _ref(method_id, 1, v1_hash))
    assert plan_v1["version"] == 1
    assert plan_v1["execution_plan_sha256"]

    # edit into v2: the same target now resolves to a different Scope category (still valid,
    # and the CBAM boundary reference is carried through the save).
    rules = [
        {
            "process_instance_id": node_id,
            "direction": "emission",
            "boundary_status": "selected",
            "location_role": "purchased_energy",
            "scope": "scope_2",
            "cbam_relevant": True,
            "classification_basis": "user",
        }
    ]
    saved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": rules,
            "cbam_boundary_ref": boundary_id,
            "expected_content_sha256": v1_hash,
        },
    )
    assert saved.status_code == 200, saved.text
    v2_hash = next(v["content_sha256"] for v in saved.json()["versions"] if v["version"] == 2)
    validated_v2 = client.post(f"/api/v1/calculation-methods/{method_id}/versions/2/validate")
    assert validated_v2.json()["valid"] is True, validated_v2.text

    # v1 is untouched: same rules -> same frozen plan, even though it is no longer the head.
    replayed = _resolve_plan(container, application["id"], revision_id, "cbam", _ref(method_id, 1, v1_hash))
    assert replayed["execution_plan_sha256"] == plan_v1["execution_plan_sha256"]

    plan_v2 = _resolve_plan(container, application["id"], revision_id, "cbam", _ref(method_id, 2, v2_hash))
    assert plan_v2["execution_plan_sha256"] != plan_v1["execution_plan_sha256"]


def test_execution_plan_rejects_wrong_hash(client, model_graph):
    import pytest

    from nebula_one.errors import DomainError

    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, _ = _ready_cbam_method(client, application, revision_id, node_id)
    container = client.app.state.container

    with pytest.raises(DomainError) as exc:
        _resolve_plan(
            container, application["id"], revision_id, "cbam",
            _ref(method_id, 1, "0" * 64),
        )
    assert exc.value.code == "CALCULATION_METHOD_HASH_MISMATCH"


def test_execution_plan_rejects_purpose_mismatch(client, model_graph):
    import pytest

    from nebula_one.errors import DomainError

    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, content_hash = _ready_cbam_method(client, application, revision_id, node_id)
    container = client.app.state.container

    with pytest.raises(DomainError) as exc:
        _resolve_plan(
            container, application["id"], revision_id, "pcf",
            _ref(method_id, 1, content_hash),
        )
    assert exc.value.code == "CALCULATION_METHOD_PURPOSE_MISMATCH"


def test_execution_plan_rejects_cross_revision_reference(client, model_graph):
    import pytest

    from nebula_one.errors import DomainError

    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, content_hash = _ready_cbam_method(client, application, revision_id, node_id)
    container = client.app.state.container

    with pytest.raises(DomainError) as exc:
        _resolve_plan(
            container, application["id"], "some-other-revision", "cbam",
            _ref(method_id, 1, content_hash),
        )
    assert exc.value.code == "CALCULATION_METHOD_REVISION_MISMATCH"


def test_execution_plan_requires_validated_version(client, model_graph):
    import pytest

    from nebula_one.errors import DomainError

    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    body = _create_method(client, application, revision_id, node_id)
    method_id = body["method"]["id"]
    draft_hash = body["versions"][0]["content_sha256"]
    container = client.app.state.container

    with pytest.raises(DomainError) as exc:
        _resolve_plan(
            container, application["id"], revision_id, "cbam",
            _ref(method_id, 1, draft_hash),
        )
    assert exc.value.code == "CALCULATION_METHOD_NOT_VALIDATED"


# --- custom (non-Scope) reporting dimensions: persist, replay, validate -------------------


_CUSTOM_DIMENSIONS = [
    {
        "id": "plant_split",
        "name": "Plant split",
        "mutually_exclusive": True,
        "requires_full_coverage": False,
        "categories": [
            {"id": "onsite_production", "name": "Onsite production", "is_leaf": True},
            {"id": "purchased_energy", "name": "Purchased energy", "is_leaf": True},
            {"id": "upstream_materials", "name": "Upstream materials", "is_leaf": True},
        ],
    }
]


def _custom_method_payload(node_id: str) -> dict:
    return {
        "name": "Plant split grouping",
        "purpose": "organization",
        "model_revision_id": None,
        "reporting_dimensions": _CUSTOM_DIMENSIONS,
        "rules": [
            {
                "process_instance_id": node_id,
                "direction": "emission",
                "boundary_status": "selected",
                "classification_basis": "user",
                "categories": {"plant_split": "onsite_production"},
            }
        ],
    }


def test_custom_reporting_dimensions_persist_and_replay(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    payload = _custom_method_payload(node_id)
    payload["model_revision_id"] = revision_id

    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods", json=payload
    )
    assert created.status_code == 201, created.text
    body = created.json()
    method_id = body["method"]["id"]
    version = body["versions"][0]
    stored_dims = version["reporting_dimensions"]
    assert [d["id"] for d in stored_dims] == ["plant_split"]
    assert sorted(c["id"] for c in stored_dims[0]["categories"]) == [
        "onsite_production",
        "purchased_energy",
        "upstream_materials",
    ]
    assert version["rules"][0]["categories"] == {"plant_split": "onsite_production"}

    reread = client.get(f"/api/v1/calculation-methods/{method_id}/versions/1").json()
    assert reread["content_sha256"] == version["content_sha256"]

    # An identical re-submit replays the head without minting a second version.
    saved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": payload["rules"],
            "reporting_dimensions": _CUSTOM_DIMENSIONS,
            "expected_content_sha256": version["content_sha256"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["latest_version"] == 1


def test_custom_dimension_method_validates_without_scope(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    payload = _custom_method_payload(node_id)
    payload["model_revision_id"] = revision_id
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods", json=payload
    ).json()
    method_id = created["method"]["id"]
    validated = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/validate"
    )
    assert validated.status_code == 200, validated.text
    body = validated.json()
    assert body["valid"] is True, body["problems"]
    assert body["status"] == "ready"


def test_validate_flags_unknown_custom_category(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    payload = _custom_method_payload(node_id)
    payload["model_revision_id"] = revision_id
    payload["rules"][0]["categories"] = {"plant_split": "not_a_declared_leaf"}
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods", json=payload
    ).json()
    method_id = created["method"]["id"]
    body = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate").json()
    assert body["valid"] is False
    assert any(p["code"] == "CALCULATION_METHOD_CATEGORY_UNKNOWN" for p in body["problems"])


def test_validate_flags_selected_rule_without_category(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    payload = _custom_method_payload(node_id)
    payload["model_revision_id"] = revision_id
    payload["rules"][0]["categories"] = {}
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods", json=payload
    ).json()
    method_id = created["method"]["id"]
    body = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate").json()
    assert body["valid"] is False
    assert any(p["code"] == "CALCULATION_METHOD_MISSING_CATEGORY" for p in body["problems"])


def test_clone_carries_custom_dimensions(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    payload = _custom_method_payload(node_id)
    payload["model_revision_id"] = revision_id
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods", json=payload
    ).json()
    method_id = created["method"]["id"]
    cloned = client.post(
        f"/api/v1/calculation-methods/{method_id}/versions/1/clone",
        json={"name": "Plant split copy", "purpose": "organization", "model_revision_id": revision_id},
    )
    assert cloned.status_code == 201, cloned.text
    cbody = cloned.json()
    assert cbody["versions"][0]["reporting_dimensions"][0]["id"] == "plant_split"
    assert cbody["versions"][0]["rules"][0]["categories"] == {"plant_split": "onsite_production"}


def test_legacy_method_without_dimensions_still_requires_scope(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Legacy organization draft",
            "purpose": "organization",
            "model_revision_id": revision_id,
            "rules": [
                {
                    "process_instance_id": node_id,
                    "direction": "emission",
                    "boundary_status": "selected",
                    "location_role": "onsite",
                    "classification_basis": "user",
                }
            ],
        },
    ).json()
    method_id = created["method"]["id"]
    body = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate").json()
    assert body["valid"] is False
    assert any(p["code"] == "CALCULATION_METHOD_MISSING_SCOPE" for p in body["problems"])



def test_execution_plan_compiles_custom_dimension(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    payload = _custom_method_payload(node_id)
    payload["model_revision_id"] = revision_id
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods", json=payload
    ).json()
    method_id = created["method"]["id"]
    v1_hash = created["versions"][0]["content_sha256"]
    client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate")

    plan = _resolve_plan(
        client.app.state.container, application["id"], revision_id, "organization",
        _ref(method_id, 1, v1_hash),
    )
    assert [d["id"] for d in plan["reporting_dimensions"]] == ["plant_split"]
    dim_ids = {d["id"] for d in plan["execution_plan"]["dimensions"]}
    assert "plant_split" in dim_ids
    target = plan["execution_plan"]["resolved_targets"][0]
    assert target["categories"]["plant_split"]["category"] == "onsite_production"
    v1_plan_hash = plan["execution_plan_sha256"]

    # Reassign the same exchange to a different declared category: the plan hash must move,
    # and the frozen v1 plan must replay unchanged (a category rename never renumbers a value).
    moved = [dict(r) for r in payload["rules"]]
    moved[0]["categories"] = {"plant_split": "purchased_energy"}
    saved = client.put(
        f"/api/v1/calculation-methods/{method_id}/versions/1",
        json={
            "rules": moved,
            "reporting_dimensions": _CUSTOM_DIMENSIONS,
            "expected_content_sha256": v1_hash,
        },
    ).json()
    assert saved["latest_version"] == 2
    v2_hash = saved["versions"][0]["content_sha256"]
    client.post(f"/api/v1/calculation-methods/{method_id}/versions/2/validate")

    plan_v2 = _resolve_plan(
        client.app.state.container, application["id"], revision_id, "organization",
        _ref(method_id, 2, v2_hash),
    )
    assert plan_v2["execution_plan_sha256"] != v1_plan_hash
    assert plan_v2["execution_plan"]["resolved_targets"][0]["categories"]["plant_split"]["category"] == "purchased_energy"

    replay_v1 = _resolve_plan(
        client.app.state.container, application["id"], revision_id, "organization",
        _ref(method_id, 1, v1_hash),
    )
    assert replay_v1["execution_plan_sha256"] == v1_plan_hash


def test_http_solve_freezes_user_grouping_method_alongside_base_characterization_method(
    client, model_graph
):
    """The backend, not only the frontend, carries the user grouping method WITH the base
    characterization method through the real /solve entry.

    A run citing both a base LCIA characterization method and an exact user grouping method must
    freeze both identities: the grouping overlay never overrides or omits the base method, and a
    run with no user grouping still freezes on the base method alone. This is the shared execution
    contract's "范围/归集规则与基础特征化方法一起传递" requirement proven over HTTP.
    """
    from nebula_one.runtime_models import SolvedSystemSnapshot

    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, content_hash = _ready_cbam_method(client, application, revision_id, node_id)
    container = client.app.state.container
    base_lcia = ["EF v3.1"]

    def _solve(payload):
        return client.post(
            f"/api/v1/applications/{application['id']}/system-revisions/{revision_id}/solve",
            json=payload,
        )

    grouped = _solve({
        "demand": [{"reference_flow_uuid": "flow-product", "amount": 1.0, "unit": "kg"}],
        "lcia_methods": base_lcia,
        "calculation_method_ref": {
            "method_id": method_id,
            "version": 1,
            "content_sha256": content_hash,
        },
    })
    assert grouped.status_code == 201, grouped.text
    with container.database.session() as db:
        row = db.get(SolvedSystemSnapshot, grouped.json()["id"])
        grouped_receipt = row.provider_receipt
    assert grouped_receipt["user_calculation_method"]["method_id"] == method_id
    assert grouped_receipt["user_calculation_method"]["version"] == 1
    assert grouped_receipt["user_calculation_method"]["content_sha256"] == content_hash
    # the base characterization method survives alongside the grouping overlay, not overridden
    assert list(grouped_receipt["calculation_basis"]["lcia_methods"]) == base_lcia

    bare = _solve({
        "demand": [{"reference_flow_uuid": "flow-product", "amount": 2.0, "unit": "kg"}],
        "lcia_methods": base_lcia,
    })
    assert bare.status_code == 201, bare.text
    with container.database.session() as db:
        bare_row = db.get(SolvedSystemSnapshot, bare.json()["id"])
        bare_receipt = bare_row.provider_receipt
    # no user grouping method selected: the run still freezes on the base method alone
    assert "user_calculation_method" not in bare_receipt
    assert list(bare_receipt["calculation_basis"]["lcia_methods"]) == base_lcia


def test_solve_revalidates_scenario_revision_binding_and_freezes_scenario_identity(
    client, model_graph
):
    """Scenario binding integrity at the shared solve entry.

    A scenario solve freezes its own scenario identity into its basis, and a scenario bound to
    another revision is refused rather than silently reused - the "每个场景独立冻结计算基础 /
    跨 revision 重新校验绑定，禁止静默复用" requirements, proven over real HTTP.
    """
    from nebula_one.runtime_models import SolvedSystemSnapshot

    application, revision_id = _setup(client, model_graph)

    def _freeze_scenario(rev) -> tuple[str, str]:
        created = client.post(
            f"/api/v1/applications/{application['id']}/scenarios",
            json={"name": "Scenario", "base_revision_id": rev, "system_revision_id": rev},
        )
        assert created.status_code == 201, created.text
        scenario_id = created.json()["id"]
        frozen = client.post(f"/api/v1/scenarios/{scenario_id}/freeze")
        assert frozen.status_code == 200, frozen.text
        return scenario_id, frozen.json()["content_sha256"]

    def _solve(rev, extra):
        return client.post(
            f"/api/v1/applications/{application['id']}/system-revisions/{rev}/solve",
            json={
                "demand": [{"reference_flow_uuid": "flow-product", "amount": 1.0, "unit": "kg"}],
                **extra,
            },
        )

    scenario_id, scenario_hash = _freeze_scenario(revision_id)

    # the scenario solve freezes its own scenario identity into its basis
    scoped = _solve(revision_id, {"scenario_id": scenario_id})
    assert scoped.status_code == 201, scoped.text
    container = client.app.state.container
    with container.database.session() as db:
        scoped_receipt = db.get(SolvedSystemSnapshot, scoped.json()["id"]).provider_receipt
    assert scoped_receipt["scenario_id"] == scenario_id
    assert scoped_receipt["scenario_hash"] == scenario_hash

    # a frozen scenario belongs to its own revision: solving it on a different revision is refused
    # at validation, before any solve or freeze, so it can never be silently reused
    second = _attach_inline_model(client, application["id"], model_graph, source_version=2)
    other_revision = second["upstream_receipt"]["base_revision_id"]
    assert other_revision != revision_id
    refused = _solve(other_revision, {"scenario_id": scenario_id})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "SCENARIO_REVISION_MISMATCH"


def _steel_variant_ref():
    from nebula_one.model_processing_contract import load_bundled_model_processing_rules

    ref = load_bundled_model_processing_rules(
        "steel-bf-bof-model-processing-1.0.12.json"
    ).reference()
    return {key: ref[key] for key in ("package_id", "version", "content_sha256")}


def test_a_method_without_a_binding_reads_back_a_null_processing_reference(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "No binding",
            "purpose": "pcf",
            "model_revision_id": revision_id,
            "rules": [{"process_instance_id": node_id, "direction": "input"}],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()["versions"][0]
    assert body["model_processing_rules_ref"] is None
    method_id = created.json()["method"]["id"]
    read = client.get(f"/api/v1/calculation-methods/{method_id}/versions/1")
    assert read.status_code == 200, read.text
    assert read.json()["model_processing_rules_ref"] is None


def test_binding_a_reviewed_package_to_a_model_with_no_template_refuses(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    rejected = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Bad binding",
            "purpose": "cbam",
            "model_revision_id": revision_id,
            "rules": [{"process_instance_id": node_id, "direction": "input"}],
            "model_processing_rules_ref": _steel_variant_ref(),
        },
    )
    # An inline model was not imported from a reviewed template, so no package is selectable for it;
    # the reference fails closed instead of being persisted, and the method is never created.
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "MODEL_PROCESSING_TEMPLATE_UNBOUND"


def test_the_selectable_packages_route_refuses_a_template_unbound_method(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json={
            "name": "Unbound method",
            "purpose": "cbam",
            "model_revision_id": revision_id,
            "rules": [{"process_instance_id": node_id, "direction": "input"}],
        },
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]
    refused = client.get(
        f"/api/v1/calculation-methods/{method_id}/selectable-processing-packages"
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "MODEL_PROCESSING_TEMPLATE_UNBOUND"


def test_the_execution_plan_surfaces_the_version_bound_processing_reference(client, model_graph):
    """The frozen execution plan carries the exact processing package a variant version binds to.

    The plan is what provider_solve derives under and what a recovered run re-checks, so the bound
    reference has to leave the contract through the plan, not only through the persisted row. The
    reference is set straight on the stored version here (an inline model has no reviewed template to
    validate a real package against), which is exactly the shape a steel variant create would persist.
    """
    from nebula_one.runtime_models import CalculationMethodVersion

    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    boundary_id = _create_boundary(client, application)
    created = client.post(
        f"/api/v1/applications/{application['id']}/calculation-methods",
        json=_cbam_rule(node_id, revision_id, boundary_id),
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]
    content_sha256 = created.json()["versions"][0]["content_sha256"]

    sample_ref = {
        "package_id": "steel-bf-bof.model-processing",
        "version": "1.0.12",
        "content_sha256": "e" * 64,
    }
    container = client.app.state.container
    with container.database.session() as db:
        record = db.scalar(
            select(CalculationMethodVersion).where(
                CalculationMethodVersion.method_id == method_id,
                CalculationMethodVersion.version == 1,
            )
        )
        record.model_processing_rules_ref = sample_ref
        db.commit()

    plan = _resolve_plan(
        container, application["id"], revision_id, "cbam",
        _ref(method_id, 1, content_sha256), require_ready=False,
    )
    assert plan["model_processing_rules_ref"] == sample_ref


def test_classification_suggestions_endpoint_derives_from_graph(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    application_id = application["id"]
    created = client.post(
        f"/api/v1/applications/{application_id}/calculation-methods",
        json={
            "name": "Suggestion preview",
            "purpose": "organization",
            "model_revision_id": revision_id,
            "rules": [],
        },
    )
    assert created.status_code == 201, created.text
    method_id = created.json()["method"]["id"]

    response = client.get(
        f"/api/v1/calculation-methods/{method_id}/versions/1/classification-suggestions"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy_version"] == "nebula_one.classification-suggestion.v1"
    assert body["method_id"] == method_id
    assert body["version"] == 1
    assert body["model_revision_id"] == revision_id
    assert body["graph_content_sha256"]
    # No package bound: the purchased input cannot be evidenced as energy, so it stays pending.
    assert body["energy_packages"] == []
    rows = {item["exchange_id"]: item for item in body["suggestions"]}
    assert rows["preparation::ore-in"]["status"] == "pending_evidence"
    assert rows["preparation::ore-in"]["suggested"]["scope"] is None
    # The internally-fed consumer input is a foreground transfer, never a Scope.
    assert rows["product::material-in"]["status"] == "not_applicable"
    assert rows["product::material-in"]["rationale"] == "foreground_internal_transfer"
    assert rows["product::product-out"]["status"] == "not_applicable"


def test_archive_retires_the_head_and_keeps_the_version_readable(client, model_graph):
    application, revision_id = _setup(client, model_graph)
    node_id = _graph_process_ids(client, revision_id)[0]
    method_id, content_hash = _ready_cbam_method(client, application, revision_id, node_id)

    archived = client.post(f"/api/v1/calculation-methods/{method_id}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "retired"

    detail = client.get(f"/api/v1/calculation-methods/{method_id}").json()
    assert detail["method"]["status"] == "retired"
    head = next(item for item in detail["versions"] if item["version"] == detail["latest_version"])
    # The ready head leaves service, so nothing can cite it for a new grouping.
    assert head["status"] == "retired"
    assert head["content_sha256"] == content_hash

    # History is not deleted: the immutable version stays readable with its exact hash.
    version = client.get(f"/api/v1/calculation-methods/{method_id}/versions/1")
    assert version.status_code == 200
    assert version.json()["content_sha256"] == content_hash
    assert version.json()["rules"]

    capabilities = client.get(f"/api/v1/calculation-methods/{method_id}/capabilities").json()
    assert capabilities["latest_status"] == "retired"


def test_archive_unknown_method_returns_404(client):
    response = client.post("/api/v1/calculation-methods/ghost/archive")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "CALCULATION_METHOD_NOT_FOUND"
