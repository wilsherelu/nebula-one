"""The whole-plant extension a steel project gets back from formal modelling, and how to label it.

Every flow identity here is one the committed steel seed already carries: the auxiliary line takes
the crop the caster already cuts and returns material through the scrap port the converter already
charges, so neither an elementary flow nor a technical flow identity is invented and no stored amount
is re-baselined. What is synthetic is the *method*: no reviewed steel clause excludes an emission
yet, so the package lives in a test namespace and every unreviewed decision says so in its clause.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache

from nebula_one.hashing import canonical_graph_sha256, canonical_json_sha256
from nebula_one.model_processing_contract import (
    MODEL_PROCESSING_SCHEMA_VERSION,
    ModelProcessingRules,
)

from test_steel_model_processing_assets import _graph, _method_package, _template_identity

UNREVIEWED = "SYNTHETIC METHOD, NOT A REVIEWED STEEL CLAUSE: "

# Committed ports the extension is built out of, so every identity it carries is one the model has.
CROP_PORT = "continuous-casting::casting-crop-out"
SCRAP_PORT = "basic-oxygen-converter::scrap-in"
ELECTRICITY_PORT = "continuous-casting::grid-electricity-in"
CO2_PORT = "ore-sintering::co2-sinter-breeze-out"
CONVERTER = "basic-oxygen-converter"

SUPPLIER_NODE = "scrap-processing-line"
SUPPLIER_UUID = "aaaaaaaa-1111-4111-8111-111111111111"

# The charge the converter keeps, the crop the caster cuts, and the bought scrap that completes it.
SCRAP_CHARGE = 150.0
CROP_CHARGE = 20.0

# A standard emission a selected core process reports and no steel clause decides on yet.
FLARE_EMISSION = f"{CONVERTER}::co2-converter-flare-out"
FLARE_AMOUNT = 25.0
# The extension line's own emission, in scope only while the line itself is inside the boundary.
VENT_EMISSION = f"{SUPPLIER_NODE}::processing-vent-out"

LINE_ACTIVITIES = ("crop_charge", "purchased_scrap", "electricity", "vented_co2", "flare_co2")


@lru_cache(maxsize=1)
def template_ports() -> dict:
    """The committed model's ports, which every identity of the extension is copied from."""
    return {
        f"{node['id']}::{port['id']}": port
        for node in _graph()["nodes"]
        for port in (*node["inputs"], *node["outputs"])
    }


def _port(source_exchange_id, port_id, name, amount, direction) -> dict:
    """One extension port, copied from a committed port so its flow identity is a real one.

    The copy keeps the source port's exact flow identity but restates ``direction`` for where the
    editor actually placed it: an added line's intake is an input even when it was modelled on a
    committed output, so the returned graph is internally valid and survives a re-solve.
    """
    port = deepcopy(template_ports()[source_exchange_id])
    port.update({"id": port_id, "name": name, "amount": amount, "direction": direction})
    return port


def _edge(edge_id, provider, source_port, consumer, target_port, amount, *, flow_from=None) -> dict:
    return {
        "id": edge_id,
        "fromNode": provider,
        "sourcePortId": source_port,
        "toNode": consumer,
        "targetPortId": target_port,
        "flowUuid": template_ports()[flow_from or f"{provider}::{source_port}"]["flowUuid"],
        "amount": amount,
        "providerAmount": amount,
        "consumerAmount": amount,
        "quantityMode": "single",
        "direction": "provider_to_consumer",
    }


def supplied_scrap(crop_charge=CROP_CHARGE, purchased_scrap=SCRAP_CHARGE - CROP_CHARGE) -> float:
    return round(crop_charge + purchased_scrap, 6)


def auxiliary_node(*, crop_charge=CROP_CHARGE, purchased_scrap=SCRAP_CHARGE - CROP_CHARGE,
                   electricity=30.0, vented_co2=3.0) -> dict:
    return {
        "id": SUPPLIER_NODE, "node_kind": "unit_process", "mode": "normalized",
        "process_uuid": SUPPLIER_UUID, "name": "Return crop and scrap processing line",
        "location": "CN", "reference_product": "material",
        "inputs": [
            _port(CROP_PORT, "crop-in", "Continuous casting crop for processing", crop_charge,
                  "input"),
            _port(SCRAP_PORT, "purchased-scrap-in", "Purchased scrap charged to the line",
                  purchased_scrap, "input"),
            _port(ELECTRICITY_PORT, "grid-electricity-in", "Grid electricity, shredding and"
                  " handling", electricity, "input"),
        ],
        "outputs": [
            _port(SCRAP_PORT, "processed-scrap-out", "Processed scrap charged to the converter",
                  supplied_scrap(crop_charge, purchased_scrap), "output"),
            _port(CO2_PORT, "processing-vent-out", "Carbon dioxide (fossil), shredder handling"
                  " vent", vented_co2, "output"),
        ],
    }


def auxiliary_edges(*, crop_charge=CROP_CHARGE,
                    purchased_scrap=SCRAP_CHARGE - CROP_CHARGE) -> list[dict]:
    return [
        _edge("edge-crop-to-scrap-line", "continuous-casting", "casting-crop-out", SUPPLIER_NODE,
              "crop-in", crop_charge),
        _edge("edge-processed-scrap-to-converter", SUPPLIER_NODE, "processed-scrap-out",
              CONVERTER, "scrap-in", supplied_scrap(crop_charge, purchased_scrap),
              flow_from=SCRAP_PORT),
    ]


def plant_extension_graph(**activities) -> dict:
    """The committed steel model plus the extension, as the professional editor would return it.

    Two things move for a process the method keeps: the converter gains a third carbon dioxide
    stream, and the scrap it already charges now arrives through the extension. The stored port
    amounts stay where the seed put them, so a comparison changes a decision rather than a model.
    """
    unknown = sorted(set(activities) - set(LINE_ACTIVITIES))
    if unknown:
        raise AssertionError(f"unknown extension activity: {unknown}")
    line = {key: value for key, value in activities.items() if key != "flare_co2"}
    graph = _graph()
    converter = next(node for node in graph["nodes"] if node["id"] == CONVERTER)
    converter["outputs"].append(
        _port(CO2_PORT, "co2-converter-flare-out",
              "Carbon dioxide (fossil), carbon burned in the converter off-gas flare",
              activities.get("flare_co2", FLARE_AMOUNT), "output")
    )
    graph["nodes"] = graph["nodes"] + [auxiliary_node(**line)]
    graph["exchanges"] = list(graph["exchanges"]) + auxiliary_edges(**line)
    return graph


def _reviewed_rules() -> list[dict]:
    package = _method_package()
    return package["manifest"]["classification_rules"]["direct_emissions"]


def _reviewed_clause() -> str:
    package = _method_package()
    return (f"restated from {package['package_id']}@{package['version']}"
            " classification_rules.direct_emissions")


def _co2_identity() -> dict:
    rule = next(item for item in _reviewed_rules() if item["exchange_id"] == CO2_PORT)
    return {key: value for key, value in rule.items()
            if key not in {"exchange_id", "process_uuid", "greenhouse_gas"}}


def _co2_decision(exchange_id, process_uuid, *, disposition, clause) -> dict:
    return dict(
        _co2_identity(),
        exchange_id=exchange_id,
        process_instance=exchange_id,
        process_uuid=process_uuid,
        greenhouse_gas="CO2",
        disposition=disposition,
        clause=clause,
    )


def _converter_uuid() -> str:
    return next(node["process_uuid"] for node in _graph()["nodes"] if node["id"] == CONVERTER)


def emission_decisions(*, exclude_flare=True, auxiliary_kept=False) -> list[dict]:
    """Every emission a kept core process carries, decided one at a time instead of pre-limited.

    The six streams the reviewed steel package already names keep their reviewed identity verbatim
    and point back at it; only the streams no clause has ever judged get a synthetic decision, so a
    reader of the report can tell a restatement from an unreviewed choice. The extension line's own
    vent is decided only while the line is inside the boundary - once selection cuts it, a decision
    naming it would be a decision about a model that no longer has it.
    """
    decisions = [
        dict(rule, disposition="include", clause=_reviewed_clause())
        for rule in _reviewed_rules()
    ]
    decisions.append(
        _co2_decision(
            FLARE_EMISSION,
            _converter_uuid(),
            disposition="exclude" if exclude_flare else "include",
            clause=UNREVIEWED + "carbon burned in the off-gas flare, which this method states sits"
                                " outside the converter process instance it is charged to",
        )
    )
    if auxiliary_kept:
        decisions.append(
            _co2_decision(
                VENT_EMISSION,
                SUPPLIER_UUID,
                disposition="include",
                clause=UNREVIEWED + "carbon from the extension line the whole-plant method keeps"
                                    " inside its process boundary",
            )
        )
    return sorted(decisions, key=lambda item: item["exchange_id"])


SYNTHETIC_PACKAGE_ID = "cbam.test.steel-whole-plant-explicit"
BORDER_SUPPLIED = f"{CONVERTER}::scrap-in"


def synthetic_manifest(decisions, *, in_boundary) -> dict:
    return {
        "schema_version": "cbam.test.whole-plant-explicit.v1",
        "capability_keys": ["cbam.trial.v2"],
        "calculation": "cbam.eu.iron-steel.bf-bof-plant-extension-synthetic",
        "product_scope": {
            "clause": UNREVIEWED + "the seed declares one crude steel product line",
            "reference_flow_uuid": "e31064bf-4268-5617-b79d-8b7f326d966e",
            "embedded_predecessors": "not_applicable",
            "precursors": "not_applicable",
            "precursor_membership": "not_applicable",
            "end_use": {"clause": UNREVIEWED + "one end use is declared", "values": ["default"]},
        },
        "boundary_schema": {
            "directness": "direct",
            "annex_ii_direct_only": False,
            "greenhouse_gases": ["CO2"],
            "production_process_boundary": {
                "clause": UNREVIEWED + "which process instances the whole-plant model keeps",
                "in_boundary_process_uuids": sorted(in_boundary),
            },
        },
        "classification_rules": {
            "mode": "explicit_flow_rules",
            "direct_emissions": [dict(item) for item in decisions],
        },
    }


def synthetic_package(decisions, *, in_boundary) -> dict:
    """A method package in the shape the deriver binds: identity plus manifest, no full registry.

    `derive_calculation_model` matches a package against the reference its rules cite by version and
    content hash only, so the synthetic package carries the same three identity keys a registered one
    would, and its hash is recomputed from its own manifest rather than claimed.
    """
    manifest = synthetic_manifest(decisions, in_boundary=in_boundary)
    return {
        "package_id": SYNTHETIC_PACKAGE_ID,
        "version": "1.0.0",
        "content_sha256": canonical_json_sha256(manifest),
        "manifest": manifest,
    }


def package_ref(package: dict) -> dict:
    return {key: package[key] for key in ("package_id", "version", "content_sha256")}


def synthetic_rules(package: dict, *, boundary_exchanges=(), template=None) -> ModelProcessingRules:
    """Rules for the extended model: a boundary the plant fits, an emission set it decides by name."""
    ref = package_ref(package)
    content = {
        "applicable_template": deepcopy(template or _template_identity()),
        "purposes": {
            "lca": {
                "process_selection": {"mode": "all_model_processes"},
                "background_disposition": {"mode": "retain_saved_pins"},
                "cross_boundary_connections": {
                    "mode": "keep_internal_edges", "boundary_exchanges": []},
                "elementary_flows": {"mode": "not_applicable"},
                "precursors": {"mode": "not_applicable"},
            },
            "cbam": {
                "process_selection": {
                    "mode": "method_package_boundary",
                    "method_package": deepcopy(ref),
                    "process_uuids_path":
                        "boundary_schema.production_process_boundary.in_boundary_process_uuids",
                },
                "background_disposition": {
                    "mode": "unlink_all_background_links",
                    "evidence": {
                        "method_package": deepcopy(ref),
                        "manifest_path": "boundary_schema.annex_ii_direct_only",
                        "required_value": False,
                        "clause": UNREVIEWED + "keeps no background supply chain",
                    },
                },
                "cross_boundary_connections": {
                    "mode": "reject_undeclared",
                    "boundary_exchanges": [
                        {
                            "exchange_id": exchange_id,
                            "disposition": "keep_as_boundary_input",
                            "amount_source": "consumer_port_amount",
                            "clause": UNREVIEWED + "the processed charge is kept as a boundary"
                                                  " input instead of following its supplier",
                        }
                        for exchange_id in boundary_exchanges
                    ],
                },
                "elementary_flows": {
                    "mode": "explicit_flow_rules",
                    "evidence": {
                        "method_package": deepcopy(ref),
                        "manifest_path": "classification_rules.direct_emissions",
                        "applicable_gases_path": "boundary_schema.greenhouse_gases",
                    },
                },
                "precursors": {"mode": "not_applicable"},
            },
        },
    }
    payload = {
        "schema_version": MODEL_PROCESSING_SCHEMA_VERSION,
        "package_id": "steel-whole-plant.model-processing",
        "version": "1.0.0",
        "license": "Apache-2.0",
        "content": content,
        "content_sha256": canonical_json_sha256(content),
    }
    return ModelProcessingRules(payload, f"synthetic:{payload['package_id']}@{payload['version']}")


def steel_boundary_uuids() -> list[str]:
    return sorted(_method_package()["manifest"]["boundary_schema"]
                  ["production_process_boundary"]["in_boundary_process_uuids"])


def provider_snapshot(project_id: str, version: int, graph: dict, **extra) -> dict:
    """The provider snapshot body the editor's engine serves for one saved model version."""
    return {
        "schema_version": "provider.snapshot.v1",
        "engine": {"version": "0.1.0", "commit": "62a51f3"},
        "project_id": project_id,
        "version": version,
        "base_snapshot_ref": {"project_id": project_id, "version": version,
                              "graph_hash": canonical_graph_sha256(graph)},
        "graph_hash": canonical_graph_sha256(graph),
        "functional_unit": {"display_text": "1 kg crude steel", "amount": 1000.0,
                            "flow_uuid": "e31064bf-4268-5617-b79d-8b7f326d966e", "unit": "kg"},
        "graph": deepcopy(graph),
        "issues": [],
        **extra,
    }
