from nebula_one.analysis.solved_mfa import (
    _resolve_label_centers,
    build_solved_mfa,
    render_sankey_svg,
)
from nebula_one.errors import DomainError


def test_internal_transfer_mismatch_fails_the_audit():
    graph = {
        "nodes": [
            {"id": "producer", "process_uuid": "p1", "name": "Producer"},
            {"id": "consumer", "process_uuid": "p2", "name": "Consumer"},
        ],
        "exchanges": [
            {
                "id": "edge-1",
                "fromNode": "producer",
                "toNode": "consumer",
                "sourcePortId": "out",
                "targetPortId": "in",
            }
        ],
    }
    solved = {
        "id": "solved-1",
        "solve_hash": "solve-hash",
        "content_sha256": "content-hash",
        "internal_transfers": [
            {
                "exchange_id": "producer::out",
                "process_id": "p1",
                "flow_uuid": "flow-1",
                "unit_group": "mass",
                "unit": "kg",
                "amount": 8.0,
            },
            {
                "exchange_id": "consumer::in",
                "process_id": "p2",
                "flow_uuid": "flow-1",
                "unit_group": "mass",
                "unit": "kg",
                "amount": 7.0,
            },
        ],
        "boundary_flows": [],
        "provider_receipt": {},
    }

    result = build_solved_mfa(solved_snapshot=solved, revision_graph=graph)

    assert result["audit"]["status"] == "failed"
    assert result["audit"]["checks"]["error_count"] == 1
    assert result["audit"]["issues"] == [
        {
            "code": "INTERNAL_TRANSFER_AMOUNT_MISMATCH",
            "severity": "error",
            "edge_id": "edge-1",
            "source_amount": 8.0,
            "target_amount": 7.0,
            "delta": 1.0,
            "tolerance": 1e-9,
        }
    ]


def test_sankey_uses_business_unit_label_and_keeps_identity_in_metadata():
    series = {
        "unit_group": "8f289843-e3f8-5d74-89b8-3e7c82d4c387",
        "unit_group_label": "Mass",
        "unit": "kg",
        "nodes": [
            {
                "id": "boundary:feed",
                "label": "Feed",
                "kind": "system_boundary",
                "direction": "input",
            },
            {"id": "process:p1", "label": "Process", "kind": "process"},
            {
                "id": "boundary:product",
                "label": "Product",
                "kind": "system_boundary",
                "direction": "output",
            },
        ],
        "links": [
            {
                "id": "feed",
                "source": "boundary:feed",
                "target": "process:p1",
                "value": 1.0,
                "kind": "boundary",
                "flow_uuid": "flow-feed",
                "flow_name": "Feed",
                "exchange_ids": ["p1::feed"],
                "exchange_type": "technosphere",
                "direction": "input",
            },
            {
                "id": "product",
                "source": "process:p1",
                "target": "boundary:product",
                "value": 1.0,
                "kind": "boundary",
                "flow_uuid": "flow-product",
                "flow_name": "Product",
                "exchange_ids": ["p1::product"],
                "exchange_type": "technosphere",
                "direction": "output",
            },
        ],
    }

    svg = render_sankey_svg(series)

    assert "Mass · kg · frozen solved exchanges" in svg
    assert (
        "unit_group_identity=8f289843-e3f8-5d74-89b8-3e7c82d4c387" in svg
    )
    assert 'data-link-id="feed"' in svg
    assert 'data-node-id="process:p1"' in svg
    assert "External inputs" in svg
    assert '<text class="column-label"' not in svg
    assert '<text class="node-role"' not in svg
    assert "IN 1 · OUT 1 kg" in svg
    assert "→ 1 kg" in svg


def test_mfa_sankey_localizes_fixed_chrome_when_chinese_labels_requested():
    series = {
        "unit_group": "8f289843-e3f8-5d74-89b8-3e7c82d4c387",
        "unit_group_label": "质量",
        "unit": "kg",
        "nodes": [
            {"id": "boundary:feed", "label": "原料", "kind": "system_boundary", "direction": "input"},
            {"id": "process:p1", "label": "过程一", "kind": "process"},
            {"id": "env:air", "label": "空气", "kind": "environment"},
            {"id": "boundary:product", "label": "产品", "kind": "system_boundary", "direction": "output"},
        ],
        "links": [
            {"id": "feed", "source": "boundary:feed", "target": "process:p1", "value": 1.0, "kind": "boundary", "flow_name": "原料", "exchange_type": "technosphere", "direction": "input"},
            {"id": "air", "source": "env:air", "target": "process:p1", "value": 0.5, "kind": "internal", "flow_name": "空气", "exchange_type": "biosphere", "direction": "input"},
            {"id": "product", "source": "process:p1", "target": "boundary:product", "value": 1.0, "kind": "boundary", "flow_name": "产品", "exchange_type": "technosphere", "direction": "output"},
        ],
    }
    zh = render_sankey_svg(series, title="物质流向图", chinese_labels=True)
    en = render_sankey_svg(series)
    # Fixed UI chrome — title, column headers, node roles, IN/OUT totals, legend, footer, subtitle —
    # renders Chinese only when the caller asks for it; every park/energy route keeps the English bytes.
    assert "物质流向图" in zh
    assert '<text class="column-label"' not in zh
    assert '<text class="node-role"' not in zh
    assert "生产过程 1" not in zh
    assert "入 1" in zh
    assert "外部投入" in zh and "环境排放" in zh
    assert "冻结求解交换" in zh
    assert "Solved MFA Sankey" not in zh
    assert "SYSTEM INPUTS" not in zh
    # Mass display labels change in both languages; the graph values are unchanged.
    assert "Solved MFA Sankey" in en
    assert '<text class="column-label"' not in en
    assert "IN 1" in en
    assert "External inputs" in en
    assert "Solved MFA Sankey" in en
    assert "物质流向图" not in en


def test_sankey_label_layout_separates_overlapping_flow_labels():
    labels = [
        {"id": "a", "x": 400.0, "y": 200.0, "width": 180.0, "height": 40.0},
        {"id": "b", "x": 430.0, "y": 205.0, "width": 180.0, "height": 40.0},
        {"id": "c", "x": 460.0, "y": 210.0, "width": 180.0, "height": 40.0},
    ]

    resolved = _resolve_label_centers(labels, min_y=120.0, max_y=360.0)

    ordered = sorted(resolved.values())
    assert ordered[1] - ordered[0] >= 46.0
    assert ordered[2] - ordered[1] >= 46.0
    assert ordered[0] >= 140.0
    assert ordered[-1] <= 340.0


MASS_UUID = "93a60a57-a4c8-11da-a746-0800200c9a66"


def _two_series_graph() -> dict:
    return {
        "nodes": [
            {"id": "m1", "process_uuid": "mp1", "name": "MP1"},
            {"id": "m2", "process_uuid": "mp2", "name": "MP2"},
            {"id": "e1", "process_uuid": "ep1", "name": "EP1"},
            {"id": "e2", "process_uuid": "ep2", "name": "EP2"},
        ],
        "exchanges": [
            {"id": "m-edge", "fromNode": "m1", "toNode": "m2", "sourcePortId": "out", "targetPortId": "in"},
            {"id": "e-edge", "fromNode": "e1", "toNode": "e2", "sourcePortId": "out", "targetPortId": "in"},
        ],
    }


def _mass_and_energy_snapshot(energy_target: float) -> dict:
    return {
        "id": "solved-two",
        "solve_hash": "solve-hash",
        "content_sha256": "content-hash",
        "internal_transfers": [
            {"exchange_id": "m1::out", "process_id": "mp1", "flow_uuid": "mf", "unit_group": MASS_UUID, "unit": "kg", "amount": 5.0, "direction": "output"},
            {"exchange_id": "m2::in", "process_id": "mp2", "flow_uuid": "mf", "unit_group": MASS_UUID, "unit": "kg", "amount": 5.0, "direction": "input"},
            {"exchange_id": "e1::out", "process_id": "ep1", "flow_uuid": "ef", "unit_group": "energy-group", "unit": "MJ", "amount": 625.0, "direction": "output"},
            {"exchange_id": "e2::in", "process_id": "ep2", "flow_uuid": "ef", "unit_group": "energy-group", "unit": "MJ", "amount": energy_target, "direction": "input"},
        ],
        "boundary_flows": [],
        "provider_receipt": {},
    }


def test_mass_series_is_selected_by_unit_group_identity_not_label():
    result = build_solved_mfa(
        solved_snapshot=_mass_and_energy_snapshot(625.0),
        revision_graph=_two_series_graph(),
    )

    by_id = {item["series_id"]: item for item in result["series"]}
    assert by_id[f"{MASS_UUID}::kg"]["is_mass"] is True
    assert by_id[f"{MASS_UUID}::kg"]["unit_group_uuid"] == MASS_UUID
    assert by_id["energy-group::MJ"]["is_mass"] is False


def test_conservation_is_scoped_per_series_so_energy_cannot_fail_mass():
    result = build_solved_mfa(
        solved_snapshot=_mass_and_energy_snapshot(600.0),
        revision_graph=_two_series_graph(),
    )

    by_id = {item["series_id"]: item for item in result["series"]}
    mass = by_id[f"{MASS_UUID}::kg"]["conservation"]
    energy = by_id["energy-group::MJ"]["conservation"]
    # an unbalanced energy transfer must not contaminate the mass view's conservation verdict
    assert energy["status"] == "failed"
    assert energy["error_count"] == 1
    assert mass["error_count"] == 0
    assert mass["status"] != "failed"
    # the global audit still aggregates every series
    assert result["audit"]["status"] == "failed"


def test_exact_background_receipt_projects_internal_energy_transfer():
    graph = {
        "nodes": [
            {
                "id": "consumer",
                "process_uuid": "consumer-process",
                "name": "Consumer",
                "inputs": [
                    {
                        "id": "electricity-in",
                        "name": "Electricity",
                        "unitGroupUuid": "energy-group",
                        "unitGroup": "Energy",
                        "unit": "MJ",
                    }
                ],
            }
        ],
        "exchanges": [],
    }
    solved = {
        "id": "solved-background",
        "solve_hash": "solve-hash",
        "content_sha256": "content-hash",
        "internal_transfers": [
            {
                "exchange_id": "provider-background::exchange-2",
                "process_id": "background-process",
                "flow_uuid": "electricity-flow",
                "unit_group": "energy-group",
                "unit": "MJ",
                "amount": 3.25,
                "direction": "output",
            },
            {
                "exchange_id": "consumer::electricity-in",
                "process_id": "consumer-process",
                "flow_uuid": "electricity-flow",
                "unit_group": "energy-group",
                "unit": "MJ",
                "amount": 3.25,
                "direction": "input",
            },
        ],
        "boundary_flows": [],
        "provider_receipt": {
            "background_process_receipts": [
                {
                    "consumer_exchange_id": "consumer::electricity-in",
                    "source_namespace": "tiangong_open_data",
                    "process_uuid": "background-process",
                    "version": "01.00.000",
                    "process_name": "CN electricity mix",
                    "claim_role": "partial_background_leaf",
                    "exchanges": [
                        {
                            "role": "quantitative_reference",
                            "expanded_exchange_id": "provider-background::exchange-2",
                            "flow_uuid": "electricity-flow",
                            "flow_name": "Electricity, medium voltage",
                            "scaled_amount": 3.25,
                        }
                    ],
                }
            ]
        },
    }

    result = build_solved_mfa(solved_snapshot=solved, revision_graph=graph)

    assert result["audit"]["status"] == "pass_with_warnings"
    assert result["audit"]["checks"]["error_count"] == 0
    assert result["audit"]["checks"]["traceable_link_count"] == 1
    assert result["audit"]["provenance"]["source_fields"] == [
        "internal_transfers",
        "boundary_flows",
        "provider_receipt.background_process_receipts",
    ]
    assert result["audit"]["provenance"][
        "background_internal_transfer_value_rule"
    ] == "exact_background_qref_scaled_amount"
    assert result["series"] == [
        {
            "series_id": "energy-group::MJ",
            "unit_group": "energy-group",
            "unit_group_uuid": "energy-group",
            "unit_group_label": "Energy",
            "is_mass": False,
            "conservation": {
                "status": "pass_with_warnings",
                "error_count": 0,
                "warning_count": 0,
                "open_boundary_count": 2,
            },
            "unit": "MJ",
            "nodes": [
                {
                    "id": "process:background-process",
                    "label": "CN electricity mix",
                    "kind": "process",
                    "process_id": "background-process",
                    "source_namespace": "tiangong_open_data",
                    "version": "01.00.000",
                    "claim_role": "partial_background_leaf",
                },
                {
                    "id": "process:consumer-process",
                    "label": "Consumer",
                    "kind": "process",
                    "process_id": "consumer-process",
                },
            ],
            "links": [
                {
                    "id": "background:consumer::electricity-in",
                    "source": "process:background-process",
                    "target": "process:consumer-process",
                    "value": 3.25,
                    "kind": "internal",
                    "origin": "background_process_receipt",
                    "flow_uuid": "electricity-flow",
                    "flow_name": "Electricity, medium voltage",
                    "exchange_ids": [
                        "provider-background::exchange-2",
                        "consumer::electricity-in",
                    ],
                    "reconciliation": {
                        "source_amount": 3.25,
                        "target_amount": 3.25,
                        "receipt_amount": 3.25,
                        "delta": 0.0,
                        "rule": "exact_background_qref_scaled_amount",
                    },
                }
            ],
            "totals": {
                "internal": 3.25,
                "boundary_input": 0,
                "boundary_output": 0,
            },
        }
    ]
    svg = render_sankey_svg(result["series"][0])
    assert "PARTIAL BACKGROUND" in svg
    assert "partial background leaf" in svg
    assert "not complete cradle-to-gate" in svg
    assert 'width="1280" height="502" viewBox="0 0 1280 502"' in svg


def test_background_receipt_mismatch_fails_solved_mfa_audit():
    graph = {
        "nodes": [{"id": "consumer", "process_uuid": "consumer-process"}],
        "exchanges": [],
    }
    solved = {
        "internal_transfers": [
            {
                "exchange_id": "provider-background::exchange-2",
                "process_id": "background-process",
                "flow_uuid": "electricity-flow",
                "unit_group": "energy-group",
                "unit": "MJ",
                "amount": 3.25,
                "direction": "output",
            },
            {
                "exchange_id": "consumer::electricity-in",
                "process_id": "consumer-process",
                "flow_uuid": "electricity-flow",
                "unit_group": "energy-group",
                "unit": "MJ",
                "amount": 3.0,
                "direction": "input",
            },
        ],
        "boundary_flows": [],
        "provider_receipt": {
            "background_process_receipts": [
                {
                    "consumer_exchange_id": "consumer::electricity-in",
                    "process_uuid": "background-process",
                    "exchanges": [
                        {
                            "role": "quantitative_reference",
                            "expanded_exchange_id": "provider-background::exchange-2",
                            "flow_uuid": "electricity-flow",
                            "scaled_amount": 3.25,
                        }
                    ],
                }
            ]
        },
    }

    result = build_solved_mfa(solved_snapshot=solved, revision_graph=graph)

    assert result["audit"]["status"] == "failed"
    assert result["audit"]["issues"][0]["code"] == "BACKGROUND_INTERNAL_TRANSFER_MISMATCH"


MASS_SERIES = ("mass-group", "kg")


def _boundary_snapshot(amounts: list[tuple[str, str, float]]) -> dict:
    """A solved snapshot whose only evidence is boundary exchanges of one unit series.

    ``amounts`` rows are ``(exchange_type, direction, amount)`` as the engine reports them.
    """
    return {
        "id": "solved-boundary",
        "solve_hash": "solve-hash",
        "content_sha256": "content-hash",
        "internal_transfers": [],
        "boundary_flows": [
            {
                "exchange_id": f"background-process::vector-{index}",
                "process_id": "background-process",
                "flow_uuid": f"flow-{index}",
                "unit_group": MASS_SERIES[0],
                "unit": MASS_SERIES[1],
                "amount": amount,
                "direction": direction,
                "exchange_type": exchange_type,
            }
            for index, (exchange_type, direction, amount) in enumerate(amounts)
        ],
        "provider_receipt": {},
    }


def _series(result: dict):
    return next(item for item in result["series"] if (item["unit_group"], item["unit"]) == MASS_SERIES)


def test_a_negative_elementary_boundary_is_drawn_as_the_opposite_direction():
    """Licensed background inventories store uptakes as a negative amount on one port.

    The ecoinvent 3.11 vector behind the steel mapped background carries three such rows
    ('Carbon dioxide, non-fossil, resource correction' as a negative input, plus negative
    'Copper ion' and 'Zinc II' outputs), so refusing them hid the whole material flow view.
    They are drawn with the opposite direction and the exact magnitude, and every case is
    recorded in the audit.
    """
    result = build_solved_mfa(
        solved_snapshot=_boundary_snapshot(
            [("elementary", "output", 3.0), ("elementary", "input", -0.5)]
        ),
        revision_graph={"nodes": [], "exchanges": []},
    )

    links = {item["exchange_ids"][0]: item for item in _series(result)["links"]}
    flipped = links["background-process::vector-1"]
    assert flipped["direction"] == "output"
    assert flipped["value"] == 0.5
    assert flipped["sign_normalization"] == {
        "source_direction": "input",
        "source_amount": -0.5,
        "rule": "negative_elementary_amount_drawn_as_opposite_direction",
    }
    assert links["background-process::vector-0"]["value"] == 3.0
    assert "sign_normalization" not in links["background-process::vector-0"]
    assert _series(result)["totals"] == {
        "internal": 0.0,
        "boundary_input": 0.0,
        "boundary_output": 3.5,
    }
    balance = next(
        item
        for item in result["audit"]["process_balances"]
        if item["process_id"] == "background-process" and item["unit"] == "kg"
    )
    assert balance["outgoing"] == 3.5
    assert balance["incoming"] == 0.0
    assert balance["residual"] == 3.5
    assert result["audit"]["issues"] == [
        {
            "code": "ELEMENTARY_EXCHANGE_SIGN_NORMALIZED",
            "severity": "warning",
            "exchange_id": "background-process::vector-1",
            "flow_uuid": "flow-1",
            "source_direction": "input",
            "source_amount": -0.5,
            "drawn_direction": "output",
            "drawn_amount": 0.5,
            "rule": "negative_elementary_amount_drawn_as_opposite_direction",
        }
    ]
    assert result["audit"]["status"] == "pass_with_warnings"
    assert result["audit"]["checks"]["error_count"] == 0
    assert result["audit"]["checks"]["warning_count"] == 1
    assert result["audit"]["provenance"]["boundary_elementary_sign_rule"] == (
        "negative_elementary_amount_drawn_as_opposite_direction"
    )


def test_a_positive_only_snapshot_records_no_sign_normalization():
    result = build_solved_mfa(
        solved_snapshot=_boundary_snapshot([("elementary", "output", 3.0)]),
        revision_graph={"nodes": [], "exchanges": []},
    )

    assert result["audit"]["issues"] == []
    assert result["audit"]["checks"]["warning_count"] == 0
    # the only process here exchanges mass with the environment, so it is an open boundary;
    # that is reported by the balance check, not by a sign normalisation.
    assert result["audit"]["status"] == "pass_with_warnings"
    assert result["audit"]["provenance"]["boundary_elementary_sign_rule"] is None


def test_a_negative_technosphere_boundary_still_refuses_the_render():
    try:
        build_solved_mfa(
            solved_snapshot=_boundary_snapshot([("technosphere", "input", -0.5)]),
            revision_graph={"nodes": [], "exchanges": []},
        )
    except DomainError as exc:
        assert exc.code == "SOLVED_MFA_AMOUNT_INVALID"
        assert "non-negative" in exc.message
        assert exc.status_code == 422
        return
    raise AssertionError("a negative technosphere boundary amount must still be refused")


def test_a_non_finite_elementary_boundary_still_refuses_the_render():
    for amount, reason in ((float("nan"), "non-negative"), (None, "invalid")):
        try:
            build_solved_mfa(
                solved_snapshot=_boundary_snapshot([("elementary", "output", amount)]),
                revision_graph={"nodes": [], "exchanges": []},
            )
        except DomainError as exc:
            assert exc.code == "SOLVED_MFA_AMOUNT_INVALID"
            assert reason in exc.message
            continue
        raise AssertionError(f"a {amount!r} elementary amount must still be refused")
