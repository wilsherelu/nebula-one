"""Expand data-defined accounting selectors onto one exact model inventory.

The output is the existing persisted per-flow rule contract. No name matching,
factor calculation, arbitrary expression, or second execution kernel is involved.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_schemas import BoundaryStatus, LocationRole, MethodDimensionSpec, RuleDirection, ScopeValue

SCHEMA_VERSION = "nebula_one.accounting-rule-definition.v1"


class PortMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange_ids: list[str] | None = Field(default=None, min_length=1)
    process_ids: list[str] | None = Field(default=None, min_length=1)
    all_model_processes: bool = False
    directions: list[RuleDirection] = Field(min_length=1)
    flow_uuids: list[str] | None = Field(default=None, min_length=1)
    contribution_target: Literal["direct", "upstream"] | None = None

    @model_validator(mode="after")
    def one_identity_selector(self):
        if sum((self.exchange_ids is not None, self.process_ids is not None, self.all_model_processes)) != 1:
            raise ValueError("exactly one exchange/process/all-model selector is required")
        for values in (self.exchange_ids, self.process_ids, self.flow_uuids, self.directions):
            if values is not None and (any(not value.strip() for value in values) or len(set(values)) != len(values)):
                raise ValueError("selector identities must be nonempty and unique")
        return self


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    boundary_status: BoundaryStatus
    scope: ScopeValue | None = None
    location_role: LocationRole = "other"
    cbam_relevant: bool = False
    categories: dict[str, str] = Field(default_factory=dict)


class AccountingSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=255)
    match: PortMatch
    classification: Classification


class AccountingRuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["nebula_one.accounting-rule-definition.v1"]
    selectors: list[AccountingSelector]
    reporting_dimensions: list[MethodDimensionSpec] = Field(default_factory=list)


def compile_accounting_selectors(definition: dict[str, Any], ports: list[dict[str, Any]],
                                base_ref: str) -> dict[str, Any]:
    """Freeze selectors to exact ports; absent identities or overlapping decisions fail closed."""
    def refuse(code: str, **details) -> None:
        raise DomainError(code=code, message="核算选择器无法绑定到当前模型，请核对方法定义。",
                          status_code=422, details=details)

    try:
        parsed = AccountingRuleDefinition.model_validate(definition)
    except ValidationError as exc:
        refuse("ACCOUNTING_RULE_DEFINITION_INVALID", problems=exc.errors(include_context=False, include_input=False))
    selector_ids = [selector.id for selector in parsed.selectors]
    if len(set(selector_ids)) != len(selector_ids):
        refuse("ACCOUNTING_SELECTOR_ID_DUPLICATE")
    port_ids = [port["exchange_id"] for port in ports]
    if len(set(port_ids)) != len(port_ids):
        refuse("ACCOUNTING_MODEL_PORT_DUPLICATE")
    rules: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = {}
    for selector in parsed.selectors:
        match = selector.match
        candidates = [port for port in ports
                      if (match.all_model_processes
                          or match.exchange_ids is not None and port["exchange_id"] in match.exchange_ids
                          or match.process_ids is not None and port["process_id"] in match.process_ids)]
        if match.exchange_ids is not None:
            missing = sorted(set(match.exchange_ids) - {p["exchange_id"] for p in candidates})
        elif match.process_ids is not None:
            missing = sorted(set(match.process_ids) - {p["process_id"] for p in candidates})
        else:
            missing = []
        if missing:
            refuse("ACCOUNTING_SELECTOR_IDENTITY_ABSENT", selector_id=selector.id, identities=missing)
        selected = []
        for port in candidates:
            target = "upstream" if port["direction"] == "input" and not port["internal"] else "direct"
            if (port["direction"] not in match.directions
                    or match.flow_uuids is not None and port.get("flow_uuid") not in match.flow_uuids
                    or match.contribution_target is not None and target != match.contribution_target):
                continue
            selected.append(port)
            rule = {**selector.classification.model_dump(), "process_instance_id": port["process_id"],
                    "exchange_id": port["exchange_id"], "flow_uuid": port.get("flow_uuid"),
                    "direction": port["direction"], "classification_basis": "package",
                    "contribution_target": target, "base_method_ref": base_ref}
            key = port["exchange_id"]
            if key in rules and rules[key] != rule:
                refuse("ACCOUNTING_SELECTOR_CONFLICT", exchange_id=key,
                       selector_ids=[*sources[key], selector.id])
            rules[key] = rule
            sources.setdefault(key, []).append(selector.id)
        if not selected:
            refuse("ACCOUNTING_SELECTOR_MATCH_EMPTY", selector_id=selector.id)
        unmatched = set(match.exchange_ids or []) - {p["exchange_id"] for p in selected}
        unmatched.update(set(match.process_ids or []) - {p["process_id"] for p in selected})
        unmatched.update(set(match.flow_uuids or []) - {p.get("flow_uuid") for p in selected})
        if unmatched:
            refuse("ACCOUNTING_SELECTOR_TARGET_MISMATCH", selector_id=selector.id, identities=sorted(unmatched))
    return {"rules": [rules[key] for key in sorted(rules)],
            "reporting_dimensions": [dimension.model_dump() for dimension in parsed.reporting_dimensions],
            "definition_sha256": canonical_json_sha256(definition),
            "rule_sources": [{"exchange_id": key, "selector_ids": sources[key]} for key in sorted(sources)]}
