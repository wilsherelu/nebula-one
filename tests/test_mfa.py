from __future__ import annotations

import copy

import pytest

from nebula_one.analysis.mfa import project_declared_mfa
from nebula_one.errors import AnalysisError


def test_declared_mfa_balances_boundary_and_internal_flow(model_graph):
    result = project_declared_mfa(model_graph)

    assert result["schema_version"] == "nebula_one.mfa.v1"
    assert result["basis"] == "nebula_lca_graph_declared_amounts"
    assert len(result["series"]) == 1
    series = result["series"][0]
    assert series["unit_group"] == "Units of mass"
    assert series["unit"] == "kg"
    assert series["totals"] == {
        "internal_flow": 8.0,
        "boundary_in": 10.0,
        "boundary_out": 10.0,
    }
    assert {item["status"] for item in series["balances"]} == {"balanced"}
    assert [item["id"] for item in series["links"]] == [
        "boundary:preparation:ore-in",
        "boundary:preparation:waste-out",
        "edge-material",
        "boundary:product:product-out",
    ]


def test_declared_mfa_rejects_unequal_dual_quantity(model_graph):
    graph = copy.deepcopy(model_graph)
    edge = graph["exchanges"][0]
    edge["quantityMode"] = "dual"
    edge["providerAmount"] = 8.0
    edge["consumerAmount"] = 7.0

    with pytest.raises(AnalysisError) as captured:
        project_declared_mfa(graph)

    assert captured.value.code == "MFA_DUAL_QUANTITY_NORMALIZATION_REQUIRED"


def test_declared_mfa_rejects_cross_unit_edge(model_graph):
    graph = copy.deepcopy(model_graph)
    graph["nodes"][1]["inputs"][0]["unit"] = "t"

    with pytest.raises(AnalysisError) as captured:
        project_declared_mfa(graph)

    assert captured.value.code == "MFA_REFERENCE_UNIT_NORMALIZATION_REQUIRED"


def test_declared_mfa_can_filter_unit_group(model_graph):
    result = project_declared_mfa(model_graph, {"unit_groups": ["Units of energy"]})

    assert result["series"] == []
    assert result["warnings"] == ["No ports matched the requested MFA scope."]
