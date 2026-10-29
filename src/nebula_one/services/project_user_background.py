"""Bind an exact user-owned LCA project version to one open inventory input."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..runtime_schemas import ProviderProjectBackgroundPin
from ..hashing import canonical_json_sha256
from ..model_processing_contract import list_model_processing_rules_for_template
from ..errors import DomainError
from .model_processing_runtime import template_identity
from .project_background import background_ports, refuse


class UserBackgroundSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consumer_exchange_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    version: int = Field(ge=1)


class ProjectUserBackgroundService:
    def __init__(self, client):
        self.client = client

    def resolve(self, graph, selection: UserBackgroundSelection, *, revision=None, application=None):
        ports = {f"{node['id']}::{port['id']}": port for node, port in background_ports(graph)}
        consumer = ports.get(selection.consumer_exchange_id)
        if consumer is None or consumer.get("amount", 0) <= 0:
            refuse("PROJECT_BACKGROUND_PORT_INVALID", "请选择尚无内部连接、数量大于零的投入。")
        snapshot = self.client.get_provider_model_snapshot(selection.project_id, selection.version).payload
        source_graph = snapshot["graph"]
        nodes = source_graph.get("nodes") or []
        identity = ("flowUuid", "flowSourceNamespace", "flowVersion", "flowPropertyUuid",
                    "flowPropertyVersion", "unitGroupUuid", "unitGroupVersion")
        edges = source_graph.get("exchanges") or []
        used_outputs = {(e.get("fromNode"), e.get("sourcePortId") or (e.get("sourceHandle") or "").removeprefix("out:")) for e in edges}
        linked_inputs = {(e.get("toNode"), e.get("targetPortId") or (e.get("targetHandle") or "").removeprefix("in:")) for e in edges}
        candidates = [(n, p) for n in nodes for p in n.get("outputs", [])
                      if p.get("type") == "technosphere" and p.get("isProduct")
                      and (n["id"], p["id"]) not in used_outputs
                      and all(consumer.get(f) and consumer.get(f) == p.get(f) for f in identity)]
        if len(candidates) != 1:
            refuse("PROJECT_BACKGROUND_FLOW_MISMATCH", "供应模型须有一个与投入精确匹配的参考产品；请检查流版本与参考产出。", match_count=len(candidates))
        node, reference = candidates[0]
        if any((n["id"], p["id"]) not in linked_inputs for n in nodes for p in n.get("inputs", []) if p.get("type") == "technosphere"):
            refuse("PROJECT_BACKGROUND_NOT_CLOSED_LEAF", "供应模型仍有未闭合上游投入，请先在建模中关联供应过程。")
        mismatches = {field: {"consumer": consumer.get(field), "provider": reference.get(field)}
                      for field in identity if not consumer.get(field) or consumer.get(field) != reference.get(field)}
        if mismatches:
            refuse("PROJECT_BACKGROUND_FLOW_MISMATCH", "供应参考产品与投入的流身份不一致。", mismatches=mismatches)
        conversion = self.client.convert_unit(from_unit=consumer["unit"], to_unit=reference["unit"],
                                              unit_group=consumer.get("unitGroup")).payload
        factor = conversion["converted_value"]
        if conversion.get("from_unit") != consumer["unit"] or conversion.get("to_unit") != reference["unit"]:
            refuse("PROJECT_BACKGROUND_UNIT_MISMATCH", "算法服务返回的单位换算身份不一致。")
        pin = ProviderProjectBackgroundPin(consumer_exchange_id=selection.consumer_exchange_id,
            project_id=selection.project_id, version=selection.version,
            expected_graph_hash=snapshot["graph_hash"], source_node_id=node["id"],
            reference_port_id=reference["id"], provider_amount_per_consumer_unit=factor,
            claim_role="user_declared_partial_background_network" if len(nodes) > 1 else "user_declared_partial_background_leaf")
        result = {"pin": pin.model_dump(mode="json"), "name": node.get("name") or selection.project_id,
                "reference_unit": reference["unit"], "consumer_unit": consumer["unit"],
                "claim_role": pin.claim_role}
        if revision is not None:
            from .returned_cbam_binding import _identity_graph
            try:
                template = template_identity(revision, application)
            except DomainError as error:
                if error.code != "MODEL_PROCESSING_TEMPLATE_UNBOUND":
                    raise
            else:
                matches = list_model_processing_rules_for_template(
                    template, graph_identity_sha256=canonical_json_sha256(_identity_graph(graph)),
                    graph=graph)
                eligible = [rules for rules in matches if "cbam" in rules.purposes and
                    rules.purpose("cbam").background_disposition.mode == "keep_declared_links_only" and
                    selection.consumer_exchange_id in rules.purpose("cbam").background_disposition.retained_consumer_exchange_ids]
                if len(eligible) == 1:
                    result["model_processing_rules_ref"] = {
                        key: eligible[0].reference()[key] for key in ("package_id", "version", "content_sha256")}
        return result

    def validate(self, graph, pins):
        for pin in pins:
            result = self.resolve(graph, UserBackgroundSelection(
                consumer_exchange_id=pin.consumer_exchange_id, project_id=pin.project_id,
                version=pin.version))
            if result["pin"] != pin.model_dump(mode="json"):
                refuse("PROJECT_BACKGROUND_PIN_CHANGED", "供应项目版本内容或单位换算已经改变，请重新关联。")
