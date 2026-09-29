from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


def canonical_json_sha256(payload: Any) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def canonical_graph_sha256(graph: dict) -> str:
    """The digest a model pin records. Deliberately plain: a stored pin must keep matching itself."""
    return canonical_json_sha256(graph)


def graph_identity_sha256(graph: dict) -> str:
    """One engine graph digested without its flow display labels.

    This is how two answers about one model are recognised as the same model, not what a pin stores.
    A pin is written once, from whichever engine answer arrived at that moment, and has to be
    recognised again for ever - but Nebula LCA rewrites the display labels of an already stored
    version from its own flow catalogue through `POST /api/projects/{id}/sync-flow-names`. Measured
    on the isolated 8007 engine with the hydrogen seed 1.3.0 on 2026-09-21: that rewrite moved
    `flow_name_en`, the port `name` and the exchange `flowName` for 16 exchanges while leaving every
    amount, unit, port id, flow uuid, direction and edge alone, which made a resumed install refuse
    its own frozen boundary.

    Nothing the solver reads can change unnoticed here, so this cannot wave away a real edit: an
    amount, a unit, a port, an edge or a flow identity still moves the digest. Independently of any
    digest, `SeedInstallationService._graph_mismatches` compares the authored process identities,
    every authored port's flow identity, amount, unit and direction, the authored edge endpoints and
    the functional unit against the engine's answer.
    """
    return canonical_json_sha256(without_display_labels(graph))


def without_display_labels(graph: dict) -> dict:
    """Return one engine graph with the fields the engine can rewrite after the version was stored."""
    stripped = copy.deepcopy(graph)
    for node in stripped.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        for group in ("inputs", "outputs"):
            for port in node.get(group) or []:
                if isinstance(port, dict):
                    port.pop("flow_name_en", None)
                    port.pop("name", None)
    for exchange in stripped.get("exchanges") or []:
        if isinstance(exchange, dict):
            exchange.pop("flow_name_en", None)
            exchange.pop("flowName", None)
    return stripped


def canonical_content_sha256(graph: dict, application_context: dict) -> str:
    return canonical_json_sha256(
        {"graph": graph, "application_context": application_context}
    )
