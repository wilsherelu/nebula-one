"""Freeze template defaults and instantiate independent, unvalidated project copies."""
from copy import deepcopy

from sqlalchemy import select

from ..errors import DomainError
from ..runtime_models import BoundaryDefinition, CalculationMethod, CalculationMethodVersion
from ..analysis.tag_grouping import CALIBER_SEMANTICS
from .calculation_methods import version_content_sha256
from .runtime_support import require_process_ids


def freeze_defaults(db, application_id, revision_id, references):
    defaults = []
    seen = set()
    for ref in references:
        method = db.get(CalculationMethod, ref.method_id)
        version = db.scalar(select(CalculationMethodVersion).where(
            CalculationMethodVersion.method_id == ref.method_id,
            CalculationMethodVersion.version == ref.version))
        if (method is None or version is None or method.application_id != application_id
                or method.model_revision_id != revision_id or method.status == "retired"
                or version.status != "ready"
                or version.content_sha256 != ref.content_sha256):
            raise DomainError(code="TEMPLATE_USER_METHOD_NOT_READY",
                              message="Select a validated method on the exact template model revision.",
                              status_code=422)
        if method.id in seen:
            raise DomainError(code="TEMPLATE_USER_METHOD_DUPLICATE",
                              message="Select only one version of each template method.", status_code=422)
        seen.add(method.id)
        if version.cbam_boundary_ref:
            boundary = db.get(BoundaryDefinition, version.cbam_boundary_ref)
            if boundary is None or boundary.application_id != application_id or boundary.status != "frozen":
                raise DomainError(code="TEMPLATE_USER_METHOD_BOUNDARY_NOT_FROZEN",
                                  message="A template method requires its own frozen boundary.", status_code=422)
        digest = version_content_sha256(method.purpose, version.cbam_boundary_ref,
            version.rules, version.reporting_dimensions, version.model_processing_rules_ref,
            version.semantics)
        if digest != ref.content_sha256:
            raise DomainError(code="TEMPLATE_USER_METHOD_HASH_MISMATCH",
                              message="The method content no longer matches its frozen identity.", status_code=409)
        defaults.append({"reference": ref.model_dump(), "name": method.name,
            "description": method.description, "purpose": method.purpose,
            "rules": deepcopy(version.rules),
            "reporting_dimensions": deepcopy(version.reporting_dimensions or []),
            "model_processing_rules_ref": deepcopy(version.model_processing_rules_ref),
            "cbam_boundary_ref": version.cbam_boundary_ref,
            **({"semantics": version.semantics} if version.semantics else {})})
    return defaults


def instantiate_defaults(db, application, revision, defaults, boundary_map):
    """Copy the frozen content, never resolve the source method's current head."""
    for default in defaults:
        require_process_ids(revision, sorted({rule["process_instance_id"] for rule in default["rules"]}))
        source_boundary = default.get("cbam_boundary_ref")
        if source_boundary and source_boundary not in boundary_map:
            raise DomainError(code="TEMPLATE_USER_METHOD_BOUNDARY_MISSING",
                              message="The method boundary was not preserved by the template.", status_code=422)
        boundary = boundary_map.get(source_boundary)
        ref = default["reference"]
        method = CalculationMethod(application_id=application.id, model_revision_id=revision.id,
            name=default["name"], description=default["description"], purpose=default["purpose"],
            origin_method_id=ref["method_id"], origin_method_version=ref["version"],
            origin_content_sha256=ref["content_sha256"], status="draft")
        db.add(method)
        db.flush()
        rules = deepcopy(default["rules"])
        dimensions = deepcopy(default["reporting_dimensions"])
        processing = deepcopy(default["model_processing_rules_ref"])
        semantics = default.get("semantics")
        db.add(CalculationMethodVersion(method_id=method.id, version=1, rules=rules,
            reporting_dimensions=dimensions, model_processing_rules_ref=processing,
            cbam_boundary_ref=boundary, status="draft", semantics=semantics,
            content_sha256=version_content_sha256(method.purpose, boundary, rules, dimensions,
                                                 processing, semantics)))


def inherit_input_tag_schemes(db, application, parent, revision):
    """Carry caliber drafts across quantity-only input revisions inside the revision transaction.

    Inputs create a new exact revision. Each active caliber (legacy tag or result category) gets an
    independent draft there, so old results keep their original method identity and the new
    quantity/background context is checked again before grouping. The operation-batch idempotency
    gate prevents duplicate copies on retry.
    """
    def port_identities(graph):
        result = {}
        for node in graph.get("nodes", []):
            for group in ("inputs", "outputs", "emissions"):
                for port in node.get(group, []):
                    key = f"{node['id']}::{port['id']}"
                    result[key] = (group, {key: value for key, value in port.items() if key != "amount"})
        return result

    before, after = port_identities(parent.graph_snapshot), port_identities(revision.graph_snapshot)
    defaults = []
    for method in db.scalars(select(CalculationMethod).where(
            CalculationMethod.application_id == application.id,
            CalculationMethod.model_revision_id == parent.id,
            CalculationMethod.status != "retired")):
        version = db.scalar(select(CalculationMethodVersion).where(
            CalculationMethodVersion.method_id == method.id
        ).order_by(CalculationMethodVersion.version.desc()).limit(1))
        if version is None or version.semantics not in CALIBER_SEMANTICS:
            continue
        for rule in version.rules:
            exchange = rule.get("exchange_id")
            if exchange not in before or before[exchange] != after.get(exchange):
                raise DomainError(code="PROJECT_TAG_IDENTITY_CHANGED",
                    message="A tagged exchange changed identity; the input revision cannot inherit its tag.",
                    status_code=409, details={"method_id": method.id, "exchange_id": exchange})
        digest = version_content_sha256(method.purpose, version.cbam_boundary_ref, version.rules,
            version.reporting_dimensions, version.model_processing_rules_ref, version.semantics)
        if digest != version.content_sha256:
            raise DomainError(code="TEMPLATE_USER_METHOD_HASH_MISMATCH",
                message="The tag scheme no longer matches its saved content identity.", status_code=409)
        defaults.append({"reference": {"method_id": method.id, "version": version.version,
            "content_sha256": digest}, "name": method.name, "description": method.description,
            "purpose": method.purpose, "semantics": version.semantics, "rules": version.rules,
            "reporting_dimensions": version.reporting_dimensions,
            "model_processing_rules_ref": version.model_processing_rules_ref,
            "cbam_boundary_ref": version.cbam_boundary_ref})
    instantiate_defaults(db, application, revision, defaults, {})
