"""Recover display labels through the exact, hashed background model in a solved receipt."""
from copy import deepcopy
from functools import lru_cache

from ..errors import DomainError


class MFADisplayGraph:
    def __init__(self, client):
        self.client = client

    @lru_cache(maxsize=128)
    def _snapshot(self, project_id, version, expected_hash):
        payload = self.client.get_provider_model_snapshot(project_id, version).payload
        if payload.get("graph_hash") != expected_hash:
            raise DomainError(code="MFA_DISPLAY_SOURCE_HASH_MISMATCH", message="Background display source differs from the frozen model hash", status_code=409)
        return payload["graph"]

    def enrich(self, graph, receipts):
        display_graph = deepcopy(graph)
        sources, issues = [], []
        for receipt in receipts:
            pin = receipt.get("pin") or {}
            try:
                source = self._snapshot(pin["project_id"], pin["version"], pin["expected_graph_hash"])
                nodes = [node for node in source.get("nodes", []) if node.get("id") == pin["source_node_id"]]
                if len(nodes) != 1 or nodes[0].get("process_uuid") != receipt.get("source_model_process_uuid", receipt.get("source_process_uuid")):
                    raise DomainError(code="MFA_DISPLAY_SOURCE_NODE_MISMATCH", message="Frozen background node identity differs", status_code=409)
                node = deepcopy(nodes[0])
                node["id"] = receipt["expanded_node_id"]
                node["process_uuid"] = receipt["source_process_uuid"]
                display_graph.setdefault("nodes", []).append(node)
                sources.append({"project_id": pin["project_id"], "version": pin["version"], "graph_hash": pin["expected_graph_hash"],
                                "source_node_id": pin["source_node_id"], "expanded_node_id": node["id"]})
            except (DomainError, KeyError) as error:
                issues.append({"code": getattr(error, "code", "MFA_DISPLAY_SOURCE_IDENTITY_INCOMPLETE"), "pin": pin})
        return display_graph, sources, issues
