"""cbam.trial.v2: closed candidate universe over a multi-process CBAM boundary.

Contract: docs/CBAM_CANDIDATE_UNIVERSE_V1.md.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from ..emission_selectors import selected_emissions
from ..hashing import canonical_graph_sha256, canonical_json_sha256
from .cbam_trial import _calendar_year, _decimal, _fail, _verified_hash


SCHEMA_VERSION = "nebula_one.cbam.trial.v2"
CAPABILITY_KEY = "cbam.trial.v2"
PACKAGE_KIND = "cbam_trial"
BOUNDARY_APPLICATION = "cbam_trial"
BOUNDARY_SCHEMA = "nebula_one.cbam.multi-process-boundary.v1"
COVERAGE_SCHEMA = "nebula_one.cbam.boundary-coverage.v1"
FORMULA_CALCULATION = "actual_specific_embedded_emissions_multi_process_direct_only"
THREE_COMPONENT_CALCULATION = (
    "actual_specific_embedded_emissions_multi_process_three_component"
)
CALCULATIONS = (FORMULA_CALCULATION, THREE_COMPONENT_CALCULATION)
DENOMINATOR_DISPOSITION = "reference_product_output_is_the_denominator"
INTERNAL_DISPOSITION = "internal_transfer_netted_inside_the_boundary"
LOSS_DISPOSITION = "loss_stream_of_an_already_counted_precursor"
PRECURSOR_DISPOSITION = "precursor_mass_counted"
INDIRECT_DISPOSITION = "indirect_electricity_counted"
NOT_APPLICABLE_DISPOSITION = "not_applicable_with_basis"
PENDING_FACTOR_DISPOSITION = "applicable_pending_factor"
ZERO_DISPOSITIONS = (NOT_APPLICABLE_DISPOSITION, INTERNAL_DISPOSITION, DENOMINATOR_DISPOSITION)
DISPOSITIONS = (
    "counted",
    PENDING_FACTOR_DISPOSITION,
    PRECURSOR_DISPOSITION,
    INDIRECT_DISPOSITION,
    "excluded_with_basis",
    NOT_APPLICABLE_DISPOSITION,
    INTERNAL_DISPOSITION,
    DENOMINATOR_DISPOSITION,
    LOSS_DISPOSITION,
    "undecided",
)
# a precursor port has no CO2 receipt and an electricity port has no emission factor, so neither can
# borrow the "counted" disposition; both must state an amount, which is what keeps them inside the
# no-silent-zero check rather than inside the zero set
AMOUNT_REQUIRED_DISPOSITIONS = (PRECURSOR_DISPOSITION, INDIRECT_DISPOSITION)
COMPONENT_BY_DISPOSITION = {
    "counted": "direct",
    PENDING_FACTOR_DISPOSITION: "indirect",
    PRECURSOR_DISPOSITION: "precursor",
    INDIRECT_DISPOSITION: "indirect",
    "excluded_with_basis": "none",
    NOT_APPLICABLE_DISPOSITION: "none",
    INTERNAL_DISPOSITION: "none",
    DENOMINATOR_DISPOSITION: "none",
    LOSS_DISPOSITION: "none",
    "undecided": "none",
}
CBAM_COMPONENTS = ("direct", "indirect", "precursors")
COMPONENT_STATUSES = ("applicable", "not_applicable_with_basis")
COMPONENT_BUCKETS = {
    "direct": "counted",
    "indirect": INDIRECT_DISPOSITION,
    "precursors": PRECURSOR_DISPOSITION,
}
EXPECTED_COMPONENT_STATES = ("complete", "formula_only", "not_applicable")
NO_RUNTIME_DECLARATION_STATE = "no_runtime_declaration_for_this_good"
# Annex I membership of a crossing input: listed and counted as precursor mass, listed but governed
# by another clause (electricity), or absent from the Annex I goods list altogether
MEMBERSHIPS = ("listed_precursor", "listed_governed_elsewhere", "not_listed")
LISTED_MEMBERSHIPS = ("listed_precursor", "listed_governed_elsewhere")
PRODUCT_FORMS = ("anhydrous", "hydrous_solution")
NITROGEN_METRIC = "kg CO2e/kg N"
CONTENT_OF_N_UNIT = "kg N / kg product"
RESULT_UNIT = "t CO2e/t product"
CONVERSION_CONTRACT = "quantity_conversion"
FLOW_SELECTION_SCHEMA = "nebula_one.model-flow-selection.v1"
FLOW_SELECTION_STATES = ("included", "excluded")
DIRECT_ONLY_FORMULA = "attributed_direct_emissions_t_CO2e / activity_level_t_product"
THREE_TERM_FORMULA = (
    "see_g = ae_g + sum(m_i x SEE_i) over Equation 62, with ae_g the three-component attributed "
    "emissions of Equation 63 and m_i = M_i / AL_g of Equation 61"
)
# the nine checks §9 adds for the three-component profile; the direct-only profile evaluates them
# too but does not echo them, because §13.7 pins that profile's published bytes
THREE_COMPONENT_CHECKS = (
    "every_component_has_clause",
    "precursor_membership_state_valid",
    "goods_complexity_derived_from_membership",
    "precursor_arithmetic_shown_per_row",
    "precursor_counted_once",
    "precursor_mass_includes_losses",
    "indirect_and_precursor_disjoint",
    "nitrogen_basis_sourced_and_dual",
    "precursor_result_identity_pinned",
)

TEN_FIELDS = (
    "source_namespace",
    "flow_uuid",
    "version",
    "flow_property_uuid",
    "flow_property_version",
    "unit_group_uuid",
    "unit_group_version",
    "unit",
    "direction",
    "compartment",
)
PORT_FIELDS = tuple(field for field in TEN_FIELDS if field != "compartment")
PORT_KEYS = {
    "source_namespace": "flowSourceNamespace",
    "flow_uuid": "flowUuid",
    "version": "flowVersion",
    "flow_property_uuid": "flowPropertyUuid",
    "flow_property_version": "flowPropertyVersion",
    "unit_group_uuid": "unitGroupUuid",
    "unit_group_version": "unitGroupVersion",
    "unit": "unit",
    "direction": "direction",
}
SOLVED_ROW_KEYS = {
    "flow_uuid": "flow_uuid",
    "unit_group_uuid": "unit_group",
    "unit": "unit",
    "direction": "direction",
}
SOLVED_ROW_FIELDS = tuple(SOLVED_ROW_KEYS)
RECEIPT_KEYS = {field: field for field in TEN_FIELDS}
# a technosphere receipt states the seven dataset identity fields plus the unit and names no
# direction or compartment at all, so those two cannot be compared against it
TECHNOSPHERE_RECEIPT_FIELDS = tuple(
    field for field in PORT_FIELDS if field != "direction"
)
PRODUCT_NULLABLE_FIELDS = ("flow_property_uuid", "flow_property_version", "compartment")
PRODUCT_REQUIRED_FIELDS = (
    *(field for field in TEN_FIELDS if field not in PRODUCT_NULLABLE_FIELDS),
    "process_uuid",
    "reference_exchange_id",
)
EMISSION_REQUIRED_FIELDS = (*TEN_FIELDS, "process_uuid", "exchange_id", "greenhouse_gas")
BOUNDARY_CONTENT_COLUMNS = (
    "name",
    "boundary_type",
    "included_entity_ids",
    "included_process_ids",
    "included_flow_rules",
    "excluded_items",
    "consolidation_policy",
    "period_id",
    "geographic_scope",
    "method_package_ref",
)
KG_PER_TONNE = Decimal("1000")


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _identity(
    expected: dict[str, Any],
    actual: dict[str, Any],
    fields: tuple[str, ...],
    key_map: dict[str, str],
    *,
    subject: str,
    exchange_id: str,
) -> None:
    mismatched: dict[str, dict[str, Any]] = {}
    for field in fields:
        observed = actual.get(key_map[field])
        if expected.get(field) != observed:
            mismatched[field] = {"method_package": expected.get(field), subject: observed}
    if mismatched:
        _fail(
            "CBAM_TRIAL_PORT_IDENTITY_DRIFT",
            f"a port identity differs between the method package and the {subject}",
            exchange_id=exchange_id,
            fields=mismatched,
        )


def _check_package(manifest: dict[str, Any]) -> dict[str, Any]:
    if (manifest.get("output_schema") or {}).get("schema_version") != SCHEMA_VERSION:
        _fail(
            "CBAM_TRIAL_OUTPUT_SCHEMA_UNSUPPORTED",
            "the v2 route requires a method package that targets cbam.trial.v2",
        )
    formula = manifest.get("formula_graph")
    if not isinstance(formula, dict) or formula.get("calculation") not in CALCULATIONS:
        _fail(
            "CBAM_TRIAL_FORMULA_UNSUPPORTED",
            "cbam.trial.v2 requires one of the declared multi-process calculations",
            accepted=list(CALCULATIONS),
        )
    three_component = formula.get("calculation") == THREE_COMPONENT_CALCULATION
    if (
        formula.get("activity_unit") != "t product"
        or formula.get("result_unit") != RESULT_UNIT
    ):
        _fail("CBAM_TRIAL_UNIT_CONTRACT_INVALID", "CBAM trial formula units are unsupported")
    if (
        formula.get("rounding") != "ROUND_HALF_EVEN"
        or formula.get("result_decimal_places") != 12
    ):
        _fail(
            "CBAM_TRIAL_ROUNDING_UNSUPPORTED",
            "CBAM trial requires the declared rounding contract",
        )

    boundary = manifest.get("boundary_schema")
    if not isinstance(boundary, dict):
        _fail(
            "CBAM_TRIAL_BOUNDARY_UNSUPPORTED",
            "CBAM trial requires an explicit Annex II direct-only boundary",
        )
    if boundary.get("application") != BOUNDARY_APPLICATION:
        _fail(
            "CBAM_TRIAL_BOUNDARY_UNSUPPORTED",
            "cbam.trial.v2 requires the package to name the boundary application it feeds",
            declared=boundary.get("application"),
        )
    if three_component:
        _check_three_component_boundary(boundary)
    else:
        if (
            boundary.get("annex_ii_direct_only") is not True
            or (boundary.get("goods_complexity") != "simple"
                and not (boundary.get("goods_complexity") == "complex"
                         and boundary.get("calculation_scope") == "direct_component_only"))
        ):
            _fail(
                "CBAM_TRIAL_BOUNDARY_UNSUPPORTED",
                "CBAM trial requires an explicit Annex II direct-only boundary",
            )
        if "emission_components" in boundary:
            _fail(
                "CBAM_TRIAL_GOODS_COMPLEXITY_MISMATCH",
                "a direct-only calculation profile declares no third-component breakdown, so an "
                "emission_components block has nothing to be checked against",
            )
    gases = boundary.get("greenhouse_gases")
    if not isinstance(gases, list) or not gases or any(not _non_empty(gas) for gas in gases):
        _fail(
            "CBAM_TRIAL_GAS_SCOPE_UNSUPPORTED",
            "cbam.trial.v2 requires the method package to list its greenhouse gases",
        )
    end_use = boundary.get("end_use")
    if not isinstance(end_use, dict) or not _non_empty(end_use.get("clause")):
        _fail(
            "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
            "cbam.trial.v2 requires the package to declare the end-use clause and its values",
        )
    if end_use.get("state") == NO_RUNTIME_DECLARATION_STATE:
        if not three_component:
            _fail(
                "CBAM_TRIAL_END_USE_UNDECLARED",
                "a direct-only good states its end use as a declaration to collect, not as a "
                "closed set with nothing to declare",
                clause=end_use.get("clause"),
            )
    elif (
        not isinstance(end_use.get("values"), list)
        or not end_use["values"]
        or any(not _non_empty(value) for value in end_use["values"])
        or not isinstance(end_use.get("not_a_cbam_good"), list)
        or any(not _non_empty(value) for value in end_use["not_a_cbam_good"])
    ):
        _fail(
            "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
            "cbam.trial.v2 requires the package to declare the end-use clause and its values",
        )
    multi = boundary.get("production_process_boundary")
    if not isinstance(multi, dict) or multi.get("schema") != BOUNDARY_SCHEMA:
        _fail(
            "CBAM_TRIAL_BOUNDARY_UNSUPPORTED",
            "cbam.trial.v2 requires the multi-process boundary object",
            provided=None if multi is None else type(multi).__name__,
        )
    for field in ("reference_process_uuid", "clause"):
        if not _non_empty(multi.get(field)):
            _fail(
                "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
                "the multi-process boundary lacks its reference process or its clause",
                field=field,
            )
    processes = multi.get("in_boundary_process_uuids")
    if (
        not isinstance(processes, list)
        or not processes
        or any(not _non_empty(uuid) for uuid in processes)
        or len(set(processes)) != len(processes)
        or multi["reference_process_uuid"] not in processes
    ):
        _fail(
            "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
            "the multi-process boundary needs a unique process set holding its reference process",
        )
    if (
        not isinstance(manifest.get("default_value_rules"), dict)
        or manifest["default_value_rules"].get("allowed") is not False
    ):
        _fail(
            "CBAM_TRIAL_DEFAULT_VALUES_UNSUPPORTED",
            "the CBAM trial accepts actual solved values only",
        )
    limitations = (manifest.get("validation_rules") or {}).get("limitations")
    if not isinstance(limitations, list) or not limitations:
        _fail(
            "CBAM_TRIAL_LIMITATIONS_REQUIRED",
            "CBAM trial method package must declare limitations",
        )
    return {
        "boundary": boundary,
        "gases": [str(gas) for gas in gases],
        "end_use": end_use,
        "multi": multi,
        "limitations": limitations,
        "three_component": three_component,
        "components": _check_components(boundary) if three_component else None,
        "nitrogen": _check_nitrogen(boundary),
    }


def _check_three_component_boundary(boundary: dict[str, Any]) -> None:
    """A three-term package states which terms the law asks for, so a leftover direct-only claim
    is not a harmless extra key: it is the opposite reading of Annex II for the same good."""
    if (
        boundary.get("annex_ii_direct_only") is True
        or "indirect_emissions" in boundary
    ):
        _fail(
            "CBAM_TRIAL_INDIRECT_NOT_APPLICABLE_BASIS_INVALID",
            "a three-component package may not also claim the Annex II direct-only carve-out, "
            "which is a property of the goods Annex II names and not of this one",
            annex_ii_direct_only=boundary.get("annex_ii_direct_only"),
            indirect_emissions=boundary.get("indirect_emissions"),
        )
    if boundary.get("goods_complexity") != "complex":
        _fail(
            "CBAM_TRIAL_GOODS_COMPLEXITY_MISMATCH",
            "a three-component calculation profile belongs to a complex good, and the package "
            "declares its goods complexity as something else",
            declared=boundary.get("goods_complexity"),
        )


def _check_components(boundary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components = boundary.get("emission_components")
    if not isinstance(components, dict) or sorted(components) != sorted(CBAM_COMPONENTS):
        _fail(
            "CBAM_TRIAL_INDIRECT_COMPONENT_MISSING",
            "a three-component package must declare all three terms of Equation 62, each with "
            "its own status",
            declared=sorted(components) if isinstance(components, dict) else None,
            required=list(CBAM_COMPONENTS),
        )
    for name in CBAM_COMPONENTS:
        entry = components[name]
        if (
            not isinstance(entry, dict)
            or entry.get("status") not in COMPONENT_STATUSES
            or not _non_empty(entry.get("clause"))
            or not _non_empty(entry.get("derivation"))
            or (
                entry["status"] == "not_applicable_with_basis"
                and not _non_empty(entry.get("basis"))
            )
        ):
            _fail(
                "CBAM_TRIAL_INDIRECT_COMPONENT_MISSING",
                "a component of Equation 62 states no status, no clause or no basis where its "
                "status requires one",
                component=name,
            )
    return {name: dict(components[name]) for name in CBAM_COMPONENTS}


def _check_nitrogen(boundary: dict[str, Any]) -> dict[str, Any] | None:
    """The nitrogen content is a regulatory denominator, so it travels as a versioned parameter with
    its own provenance rather than as a number the analyzer could hold anywhere."""
    nitrogen = boundary.get("nitrogen_basis")
    if nitrogen is None:
        return None
    if not isinstance(nitrogen, dict) or nitrogen.get("applies") is not True:
        _fail(
            "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
            "a package that declares a nitrogen basis must state that it applies",
        )
    for field in ("clause", "legal_denominator", "metric"):
        if not _non_empty(nitrogen.get(field)):
            _fail(
                "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
                "the nitrogen basis declares no clause, legal denominator or metric",
                field=field,
            )
    if nitrogen["metric"] != NITROGEN_METRIC:
        _fail(
            "CBAM_TRIAL_NITROGEN_BASIS_CN_NOT_LISTED",
            "the nitrogen metric is not the per-kilogram-of-nitrogen unit A-C18 measures this "
            "good on",
            declared=nitrogen["metric"],
            required=NITROGEN_METRIC,
        )
    codes = nitrogen.get("applicable_cn_codes")
    if (
        not isinstance(codes, list)
        or not codes
        or any(not _non_empty(code) for code in codes)
        or len(set(codes)) != len(codes)
    ):
        _fail(
            "CBAM_TRIAL_NITROGEN_BASIS_CN_NOT_LISTED",
            "the nitrogen basis carries no versioned set of the CN codes A-C18 lists it for",
        )
    if str(boundary.get("cn_code") or "") not in [str(code) for code in codes]:
        _fail(
            "CBAM_TRIAL_NITROGEN_BASIS_CN_NOT_LISTED",
            "this good's CN code is outside the set A-C18 lists the nitrogen denominator for, "
            "so no nitrogen-basis result field may be generated for it",
            cn_code=boundary.get("cn_code"),
            listed=codes,
        )
    parameter = nitrogen.get("content_of_n")
    if not isinstance(parameter, dict):
        _fail(
            "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
            "the nitrogen basis names no content_of_n parameter record",
        )
    for field in (
        "value",
        "unit",
        "claim_level",
        "product_form",
        "derivation_route",
        "parameter_ref",
    ):
        if not _non_empty(parameter.get(field)):
            _fail(
                "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
                "the content_of_n parameter record states no value, unit, claim level, product "
                "form, derivation route or seed parameter reference",
                field=field,
            )
    if parameter["unit"] != CONTENT_OF_N_UNIT:
        _fail(
            "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
            "the content of nitrogen is not declared on kilograms of contained element per "
            "kilogram of product, so it cannot divide a per-tonne result into A-C18's denominator",
            unit=parameter["unit"],
            required=CONTENT_OF_N_UNIT,
        )
    if "concentration" not in parameter:
        _fail(
            "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
            "the content_of_n record must state its concentration explicitly, null included, "
            "so an omitted one cannot be read as a measured absence",
        )
    if parameter["claim_level"] not in ("measured", "derived_stoichiometric"):
        _fail(
            "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
            "the content of nitrogen is neither a measured value nor a declared derivation",
            claim_level=parameter["claim_level"],
        )
    if parameter["product_form"] not in PRODUCT_FORMS:
        _fail(
            "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
            "the product form the nitrogen content is measured against is undeclared",
            product_form=parameter["product_form"],
        )
    if parameter["product_form"] == "hydrous_solution" and not _non_empty(
        parameter.get("concentration")
    ):
        _fail(
            "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
            "an aqueous product must report its concentration with the content of nitrogen",
            product_form=parameter["product_form"],
        )
    _decimal(parameter["value"], field="nitrogen_basis.content_of_n.value")
    if not _non_empty(parameter.get("published_source_sha256")):
        _fail(
            "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
            "the content of nitrogen names no published source hash, so it has no provenance",
        )
    labels = nitrogen.get("labels")
    if (
        not isinstance(labels, dict)
        or sorted(labels) != ["per_kg_n", "per_tonne_product"]
        or any(not _non_empty(labels[name]) for name in labels)
    ):
        _fail(
            "CBAM_TRIAL_RESULT_FIELD_INCOMPLETE",
            "a nitrogen basis must label both metrics it puts side by side, because an "
            "unlabelled pair is how one of them quietly replaces the other",
            declared=sorted(labels) if isinstance(labels, dict) else None,
        )
    adjustment = nitrogen.get("composition_adjustment")
    if not isinstance(adjustment, dict) or not isinstance(adjustment.get("applied"), bool):
        _fail(
            "CBAM_TRIAL_COMPOSITION_ADJUSTMENT_WITHOUT_RANGE",
            "the nitrogen basis must state whether A-C23's composition adjustment is applied",
        )
    if adjustment["applied"] and not isinstance(adjustment.get("composition_range"), dict):
        _fail(
            "CBAM_TRIAL_COMPOSITION_ADJUSTMENT_WITHOUT_RANGE",
            "a composition adjustment is declared applied without the range Equation 65/66 "
            "operates inside",
        )
    return {**nitrogen, "content_of_n": dict(parameter), "labels": dict(labels)}


def _check_rules(
    manifest: dict[str, Any], in_boundary: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rules = manifest.get("classification_rules")
    product = rules.get("product") if isinstance(rules, dict) else None
    emissions = rules.get("direct_emissions") if isinstance(rules, dict) else None
    if not isinstance(product, dict) or not isinstance(emissions, list) or not emissions:
        _fail(
            "CBAM_TRIAL_CLASSIFICATION_INVALID",
            "cbam.trial.v2 requires one product rule and at least one direct-emission rule",
        )
    for field in PRODUCT_REQUIRED_FIELDS:
        if field in PRODUCT_NULLABLE_FIELDS:
            if field not in product:
                _fail(
                    "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
                    "the product rule must state a nullable identity field as null explicitly",
                    field=field,
                )
        elif not _non_empty(product.get(field)):
            _fail(
                "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
                "the product rule lacks exact identity",
                field=field,
            )
    seen: set[str] = set()
    for rule in emissions:
        if not isinstance(rule, dict):
            _fail("CBAM_TRIAL_CLASSIFICATION_INVALID", "a direct-emission rule is not an object")
        for field in EMISSION_REQUIRED_FIELDS:
            if field not in rule:
                _fail(
                    "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
                    "a direct-emission rule omits an identity field",
                    exchange_id=rule.get("exchange_id"),
                    field=field,
                )
            if not _non_empty(rule.get(field)):
                _fail(
                    "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
                    "a direct-emission rule lacks exact identity",
                    exchange_id=rule.get("exchange_id"),
                    field=field,
                )
        exchange_id = str(rule["exchange_id"])
        if exchange_id in seen:
            _fail(
                "CBAM_TRIAL_DOUBLE_COUNT",
                "the same exchange is claimed by two direct-emission rules",
                exchange_id=exchange_id,
            )
        seen.add(exchange_id)
        if rule["process_uuid"] not in in_boundary:
            _fail(
                "CBAM_TRIAL_BOUNDARY_MISMATCH",
                "a counted emission sits outside the declared multi-process boundary",
                exchange_id=exchange_id,
                process_uuid=rule["process_uuid"],
            )
        if rule["unit"] != "kg" or rule["direction"] != "output":
            _fail(
                "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
                "a direct-emission rule must be an outgoing flow measured in kg",
                exchange_id=exchange_id,
            )
    return product, emissions


def _identity_selected_rules(
    manifest: dict[str, Any], frozen_graph: dict[str, Any], in_boundary: list[str],
    base_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve reviewed selectors against the frozen graph; retain actual ids as evidence."""
    selectors = (manifest.get("classification_rules") or {}).get(
        "additional_direct_emission_selectors")
    if selectors is None:
        return base_rules
    if not isinstance(selectors, list) or not selectors:
        _fail("CBAM_TRIAL_CLASSIFICATION_INVALID", "the additional emission selectors are invalid")
    resolved = list(base_rules)
    seen = {str(rule["exchange_id"]) for rule in base_rules}
    for selector in selectors:
        identity = selector.get("identity") if isinstance(selector, dict) else None
        if not isinstance(identity, dict) or identity.get("process_uuid") not in in_boundary:
            _fail("CBAM_TRIAL_BOUNDARY_MISMATCH",
                  "an additional emission selector has no in-boundary process identity")
        for exchange_id, _, _ in selected_emissions(frozen_graph, identity):
            if exchange_id in seen:
                _fail("CBAM_TRIAL_DOUBLE_COUNT",
                      "a graph emission matches two direct-emission declarations",
                      exchange_id=exchange_id)
            rule = {**identity, "exchange_id": exchange_id}
            if any(field not in rule or not _non_empty(rule[field])
                   for field in EMISSION_REQUIRED_FIELDS):
                _fail("CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
                      "an additional emission selector lacks exact identity",
                      exchange_id=exchange_id)
            seen.add(exchange_id)
            resolved.append(rule)
    return resolved


def _flow_selection(
    flow_selection: dict[str, Any] | None,
    *,
    method_package_ref: str,
    method_package_sha256: str,
    declared_counted: set[str],
    ports: dict[str, dict[str, Any]],
    ledger: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Bind the counted emission set to the reviewed selection the calculation model was derived with.

    A whole-plant model may hold emissions the method does not count, and the derivation cuts them out
    of the graph it hands the engine. Reading a solved answer then has to count the same set those same
    reviewed rules kept: resolving a second list here would let a trial report a number for exchanges
    nothing classified, or drop exchanges the calculation model was solved with.
    """
    if flow_selection is None:
        return None
    if (
        not isinstance(flow_selection, dict)
        or flow_selection.get("schema_version") != FLOW_SELECTION_SCHEMA
        or flow_selection.get("mode") not in ("explicit_flow_rules", "identity_selector_rules")
    ):
        _fail(
            "CBAM_TRIAL_FLOW_SELECTION_UNSUPPORTED",
            "a purpose-derived CBAM trial must carry the reviewed emission selection its calculation"
            " model was derived with, in the shape the derivation records it",
            flow_selection=flow_selection,
        )
    package = flow_selection.get("method_package")
    if not isinstance(package, dict) or not all(
        _non_empty(package.get(key)) for key in ("package_id", "version", "content_sha256")
    ):
        _fail(
            "CBAM_TRIAL_FLOW_SELECTION_INVALID",
            "the reviewed emission selection names no exact method package",
            method_package=package,
        )
    if (
        f"{package['package_id']}@{package['version']}" != str(method_package_ref)
        or package["content_sha256"] != str(method_package_sha256)
    ):
        _fail(
            "CBAM_TRIAL_FLOW_SELECTION_METHOD_MISMATCH",
            "the emission selection was reviewed under another method package than the one this trial"
            " counts with, so the two could not describe one calculation",
            selection_method_package=f"{package['package_id']}@{package['version']}",
            selection_content_sha256=package["content_sha256"],
            trial_method_package_ref=str(method_package_ref),
            trial_content_sha256=str(method_package_sha256),
        )
    decisions = flow_selection.get("decisions")
    if not isinstance(decisions, list) or not all(isinstance(item, dict) for item in decisions):
        _fail(
            "CBAM_TRIAL_FLOW_SELECTION_INVALID",
            "the reviewed emission selection carries no per-exchange decisions",
            decisions=decisions,
        )
    decided: dict[str, dict[str, Any]] = {}
    for item in decisions:
        exchange_id = str(item.get("exchange_id") or "")
        state = str(item.get("state") or "")
        if (
            not exchange_id
            or state not in FLOW_SELECTION_STATES
            or not _non_empty(item.get("clause"))
        ):
            _fail(
                "CBAM_TRIAL_FLOW_SELECTION_INVALID",
                "an emission decision states no exchange, a state outside the reviewed set or no"
                " clause that justifies it",
                exchange_id=exchange_id or None,
                state=state or None,
            )
        if exchange_id in decided:
            _fail(
                "CBAM_TRIAL_FLOW_SELECTION_INVALID",
                "the reviewed emission selection decides one exchange twice",
                exchange_id=exchange_id,
            )
        decided[exchange_id] = item
    included = {key for key, item in decided.items() if item["state"] == "included"}
    excluded = set(decided) - included
    if included != {
        str(value) for value in flow_selection.get("included_exchange_ids") or []
    } or excluded != {str(value) for value in flow_selection.get("excluded_exchange_ids") or []}:
        _fail(
            "CBAM_TRIAL_FLOW_SELECTION_INVALID",
            "the per-exchange decisions disagree with the exchange ids the selection names as"
            " counted or cut",
            included=sorted(included),
            excluded=sorted(excluded),
            declared_included=sorted(str(v) for v in flow_selection.get("included_exchange_ids") or []),
            declared_excluded=sorted(str(v) for v in flow_selection.get("excluded_exchange_ids") or []),
        )
    if included != declared_counted:
        _fail(
            "CBAM_TRIAL_FLOW_SELECTION_MISMATCH",
            "the emissions this method package counts are not the ones the reviewed selection kept"
            " for this calculation model, so the answer would be read from another boundary than the"
            " one that was solved",
            reviewed_selection=sorted(included),
            method_package=sorted(declared_counted),
        )
    leaked = sorted(excluded & set(ports))
    if leaked:
        _fail(
            "CBAM_TRIAL_FLOW_SELECTION_NOT_APPLIED",
            "an emission the reviewed selection excludes is still part of the calculation model this"
            " snapshot solved, so this reading is computing from the whole stored model",
            exchange_ids=leaked,
        )
    unagreed = sorted(
        exchange_id
        for exchange_id in excluded
        if (ledger.get(exchange_id) or {}).get("disposition") != "excluded_with_basis"
    )
    if unagreed:
        _fail(
            "CBAM_TRIAL_FLOW_SELECTION_MISMATCH",
            "the reviewed selection excludes an emission the frozen boundary does not record as"
            " excluded, so the two bases classify different universes",
            exchange_ids=unagreed,
            frozen_boundary={
                exchange_id: (ledger.get(exchange_id) or {}).get("disposition")
                for exchange_id in unagreed
            },
        )
    return {
        "included": included,
        "excluded": excluded,
        "decisions": decisions,
        "method_package": package,
        "manifest_path": flow_selection.get("manifest_path"),
    }


def _frozen_identity(
    *,
    frozen_graph: dict[str, Any],
    revision_identity: dict[str, Any],
    provider_receipt: dict[str, Any],
) -> dict[str, Any]:
    snapshot_ref = provider_receipt.get("snapshot_ref")
    if not isinstance(snapshot_ref, dict):
        _fail(
            "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
            "the solved snapshot carries no reference to a frozen model",
        )
    recomputed = canonical_graph_sha256(frozen_graph)
    # One and the provider hash the same graph to different values, so a hash is only
    # ever compared against records written by the same hasher.
    pairs = {
        "project_id": (snapshot_ref.get("project_id"), revision_identity.get("upstream_project_id")),
        "version": (snapshot_ref.get("version"), revision_identity.get("upstream_version")),
        "graph_sha256": (revision_identity.get("graph_sha256"), recomputed),
    }

    def agrees(pair: tuple[Any, Any]) -> bool:
        wanted, found = pair
        return (
            wanted is not None
            and str(wanted) != ""
            and found is not None
            and str(wanted) == str(found)
        )

    mismatched = {
        name: {"expected": wanted, "actual": found}
        for name, (wanted, found) in pairs.items()
        if not agrees((wanted, found))
    }
    if mismatched:
        _fail(
            "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
            "the frozen graph One holds is not the model this snapshot was solved from",
            fields=mismatched,
        )
    if not _non_empty(snapshot_ref.get("graph_hash")):
        _fail(
            "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
            "the solved snapshot names a model version without its provider graph hash",
            project_id=snapshot_ref.get("project_id"),
            version=snapshot_ref.get("version"),
        )
    provenance = provider_receipt.get("provenance")
    consumer_graph_hash = (
        str(provenance.get("consumer_graph_hash") or "")
        if isinstance(provenance, dict)
        else ""
    )
    if consumer_graph_hash and consumer_graph_hash != str(snapshot_ref["graph_hash"]):
        _fail(
            "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
            "the solve names one model in snapshot_ref and another in its own provenance",
            snapshot_ref_graph_hash=str(snapshot_ref["graph_hash"]),
            provenance_consumer_graph_hash=consumer_graph_hash,
        )
    return {
        "system_revision_id": revision_identity.get("system_revision_id"),
        "graph_sha256": str(revision_identity["graph_sha256"]),
        "recomputed_graph_sha256": recomputed,
        "upstream_project_id": str(revision_identity["upstream_project_id"]),
        "upstream_version": revision_identity["upstream_version"],
        "provider_project_id": str(snapshot_ref["project_id"]),
        "provider_version": snapshot_ref["version"],
        "engine_graph_hash": str(snapshot_ref["graph_hash"]),
        "engine_provenance_graph_hash": consumer_graph_hash or None,
    }


def _nodes_in_boundary(
    frozen_graph: dict[str, Any], processes: list[str]
) -> dict[str, str]:
    node_by_uuid: dict[str, str] = {}
    for node in frozen_graph.get("nodes") or []:
        if not isinstance(node, dict):
            _fail(
                "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                "the frozen graph holds a node that is not an object",
            )
        node_id = str(node.get("id") or "")
        process_uuid = str(node.get("process_uuid") or "")
        if not node_id or not process_uuid:
            _fail(
                "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                "a frozen graph node has no id or no process_uuid",
                node_id=node_id,
            )
        if process_uuid in node_by_uuid:
            _fail(
                "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                "one process uuid resolves to two graph nodes",
                process_uuid=process_uuid,
                node_ids=sorted({node_by_uuid[process_uuid], node_id}),
            )
        node_by_uuid[process_uuid] = node_id
    missing = sorted(set(processes) - set(node_by_uuid))
    if missing:
        _fail(
            "CBAM_TRIAL_BOUNDARY_PROCESS_UNKNOWN",
            "the frozen boundary names processes the frozen model does not contain",
            process_uuids=missing,
            known=sorted(node_by_uuid),
        )
    return {node_by_uuid[uuid]: uuid for uuid in processes}


def _enumerate_ports(
    frozen_graph: dict[str, Any], nodes_in_boundary: dict[str, str]
) -> dict[str, dict[str, Any]]:
    ports: dict[str, dict[str, Any]] = {}
    for node in frozen_graph.get("nodes") or []:
        node_id = str(node.get("id"))
        if node_id not in nodes_in_boundary:
            continue
        for collection in ("inputs", "outputs"):
            for port in node.get(collection) or []:
                if not isinstance(port, dict):
                    _fail(
                        "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                        "a frozen graph node holds a port that is not an object",
                        node_id=node_id,
                    )
                port_id = str(port.get("id") or "")
                exchange_id = f"{node_id}::{port_id}"
                if not port_id or exchange_id in ports:
                    _fail(
                        "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                        "a frozen graph port has no id or appears twice",
                        exchange_id=exchange_id,
                    )
                ports[exchange_id] = {
                    "exchange_id": exchange_id,
                    "node_id": node_id,
                    "port_id": port_id,
                    "process_uuid": nodes_in_boundary[node_id],
                    "type": str(port.get("type") or ""),
                    "direction": str(port.get("direction") or ""),
                    "port": port,
                }
    return ports


def _internal_transfers(
    frozen_graph: dict[str, Any],
    ports: dict[str, dict[str, Any]],
    nodes_in_boundary: dict[str, str],
) -> dict[str, str]:
    endpoints = {
        (entry["node_id"], entry["port_id"]): exchange_id
        for exchange_id, entry in ports.items()
    }
    inside = set(nodes_in_boundary)
    internal: dict[str, str] = {}
    for edge in frozen_graph.get("exchanges") or []:
        if not isinstance(edge, dict):
            _fail(
                "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                "the frozen graph holds an exchange that is not an object",
            )
        if edge.get("type") != "technosphere":
            continue
        provider = endpoints.get((str(edge.get("fromNode")), str(edge.get("sourcePortId"))))
        consumer = endpoints.get((str(edge.get("toNode")), str(edge.get("targetPortId"))))
        if provider is None or consumer is None:
            _fail(
                "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                "a frozen graph edge references a port the model does not have",
                edge_id=edge.get("id"),
            )
        if str(edge.get("fromNode")) not in inside or str(edge.get("toNode")) not in inside:
            continue
        if provider in internal or consumer in internal:
            _fail(
                "CBAM_TRIAL_DOUBLE_COUNT",
                "a port sits on two internal transfers at once",
                exchange_ids=sorted({provider, consumer}),
            )
        internal[provider] = consumer
        internal[consumer] = provider
    return internal


def _categories(
    ports: dict[str, dict[str, Any]], internal: dict[str, str]
) -> dict[str, str]:
    categories: dict[str, str] = {}
    for exchange_id, entry in ports.items():
        if entry["type"] == "biosphere":
            categories[exchange_id] = "elementary"
        elif entry["type"] == "technosphere":
            categories[exchange_id] = "internal" if exchange_id in internal else "crossing"
        else:
            _fail(
                "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                "a frozen graph port declares no exchange type",
                exchange_id=exchange_id,
                type=entry["type"],
            )
    return categories


def _dispositions(boundary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    entries = [
        *(boundary.get("included_flow_rules") or []),
        *(boundary.get("excluded_items") or []),
    ]
    for entry in entries:
        if not isinstance(entry, dict):
            _fail(
                "CBAM_TRIAL_BOUNDARY_MISMATCH",
                "the frozen boundary holds a disposition that is not an object",
            )
        exchange_id = str(entry.get("exchange_id") or "")
        if not exchange_id:
            _fail(
                "CBAM_TRIAL_BOUNDARY_MISMATCH",
                "a frozen boundary disposition names no exchange",
            )
        if exchange_id in index:
            _fail(
                "CBAM_TRIAL_CANDIDATE_PORT_CLASSIFIED_TWICE",
                "the frozen boundary classifies one exchange twice",
                exchange_id=exchange_id,
            )
        index[exchange_id] = entry
    return index


def _resolve_end_use(
    *,
    declaration: dict[str, Any],
    boundary: dict[str, Any],
    request_value: str | None,
) -> dict[str, Any]:
    clause = str(declaration["clause"])
    if declaration.get("state") == NO_RUNTIME_DECLARATION_STATE:
        if request_value is not None:
            _fail(
                "CBAM_TRIAL_END_USE_DECLARATION_CONFLICT",
                "the method package states that this good has no end-use declaration to collect, "
                "so a request that supplies one is restating a threshold the law does not set",
                clause=clause,
                requested=str(request_value),
            )
        return {
            "clause": clause,
            "declared": None,
            "state": NO_RUNTIME_DECLARATION_STATE,
            "basis": declaration.get("basis"),
            "source": "method_package_declaration_state",
            "restated_in_request": False,
        }
    frozen = [
        entry
        for entry in (boundary.get("consolidation_policy") or {}).get("runtime_declarations") or []
        if isinstance(entry, dict) and entry.get("clause") == clause
    ]
    if len(frozen) != 1:
        _fail(
            "CBAM_TRIAL_BOUNDARY_MISMATCH",
            "the frozen boundary must declare the end-use clause exactly once",
            clause=clause,
            matches=len(frozen),
        )
    authoritative = frozen[0].get("declared")
    if not _non_empty(authoritative):
        _fail(
            "CBAM_TRIAL_END_USE_UNDECLARED",
            "the frozen boundary holds no end-use declaration for this clause",
            clause=clause,
        )
    authoritative = str(authoritative)
    if request_value is not None and str(request_value) != authoritative:
        _fail(
            "CBAM_TRIAL_END_USE_DECLARATION_CONFLICT",
            "the request restates an end use the frozen boundary does not hold",
            clause=clause,
            frozen=authoritative,
            requested=str(request_value),
        )
    if authoritative not in [str(value) for value in declaration["values"]]:
        _fail(
            "CBAM_TRIAL_END_USE_VALUE_UNSUPPORTED",
            "the declared end use is outside the values the method package accepts",
            clause=clause,
            declared=authoritative,
            accepted=declaration["values"],
        )
    if authoritative in [str(value) for value in declaration["not_a_cbam_good"]]:
        _fail(
            "CBAM_TRIAL_NOT_A_CBAM_GOOD",
            "the frozen declaration excludes this product from CBAM goods under the selected method package",
            clause=clause,
            declared=authoritative,
        )
    if authoritative in declaration.get("unsupported_model_boundaries", []):
        _fail("CBAM_TRIAL_MODEL_BOUNDARY_UNSUPPORTED", "该生产边界需要当前案例未覆盖的工序和排放，不能只更改用途标签。", declared=authoritative)
    return {
        "clause": clause,
        "declared": authoritative,
        "source": "frozen_boundary_definition",
        "restated_in_request": request_value is not None,
    }


def _record_membership(entry: dict[str, Any], *, tri_state: bool) -> dict[str, Any]:
    """Read one precursor membership record as a tri-state, or refuse it.

    A boolean-only record is the shape the released direct-only package publishes (defect D-A6 stays
    open there), so it is accepted on that profile and echoed unchanged. On the three-component
    profile a boolean cannot say "listed, but another clause governs it", which is exactly the
    distinction A-C21 draws for electricity, so the tri-state is required.
    """
    flow_uuid = str(entry.get("flow_uuid") or "")
    listed = entry.get("annex_i_listed")
    if not isinstance(listed, bool):
        _fail(
            "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
            "a precursor membership record states no boolean Annex I reading",
            flow_uuid=flow_uuid or None,
        )
    membership = entry.get("membership")
    if membership is None:
        if tri_state:
            _fail(
                "CBAM_TRIAL_PRECURSOR_MEMBERSHIP_STATE_UNSUPPORTED",
                "a three-component package records a crossing input by boolean alone, which "
                "cannot tell a counted precursor from a flow an Annex II clause governs elsewhere",
                flow_uuid=flow_uuid or None,
            )
        return {"membership": None, "annex_i_listed": listed, "governing_clause": None}
    if membership not in MEMBERSHIPS:
        _fail(
            "CBAM_TRIAL_PRECURSOR_MEMBERSHIP_STATE_UNSUPPORTED",
            "a precursor membership state is outside the closed tri-state set",
            flow_uuid=flow_uuid or None,
            membership=membership,
            accepted=list(MEMBERSHIPS),
        )
    if listed != (membership in LISTED_MEMBERSHIPS):
        _fail(
            "CBAM_TRIAL_PRECURSOR_MEMBERSHIP_STATE_UNSUPPORTED",
            "the derived Annex I boolean contradicts the tri-state membership it claims to "
            "restate, so one of the two is not the reading of the Annex I list",
            flow_uuid=flow_uuid or None,
            membership=membership,
            annex_i_listed=listed,
        )
    governing = entry.get("governing_clause")
    if membership == "listed_governed_elsewhere" and not _non_empty(governing):
        _fail(
            "CBAM_TRIAL_PRECURSOR_MEMBERSHIP_STATE_UNSUPPORTED",
            "a flow recorded as listed but governed elsewhere names no governing clause, which "
            "is the only thing that keeps it out of the precursor term",
            flow_uuid=flow_uuid or None,
        )
    return {
        "membership": str(membership),
        "annex_i_listed": listed,
        "governing_clause": governing,
    }


def _membership_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The package's Annex I membership records, indexed by the flow identity each one names.

    Membership is a statement about a flow, not about a port, so a flow recorded twice has no
    reading to pick between: that is a package defect rather than a modelling choice.
    """
    rules = manifest.get("precursor_rules")
    evidence = rules.get("membership_evidence") if isinstance(rules, dict) else None
    if not isinstance(evidence, list) or not evidence:
        _fail(
            "CBAM_TRIAL_PRECURSOR_UNDECIDED",
            "cbam.trial.v2 needs the method package to record precursor membership evidence",
        )
    by_flow: dict[str, dict[str, Any]] = {}
    for entry in evidence:
        if not isinstance(entry, dict) or not _non_empty(entry.get("flow_uuid")):
            _fail(
                "CBAM_TRIAL_PRECURSOR_UNDECIDED",
                "a precursor membership record states no flow identity",
            )
        flow_uuid = str(entry["flow_uuid"])
        if flow_uuid in by_flow:
            _fail(
                "CBAM_TRIAL_PRECURSOR_UNDECIDED",
                "a precursor membership record is declared twice with no order to pick",
                flow_uuid=flow_uuid,
            )
        by_flow[flow_uuid] = entry
    return by_flow


def is_multi_process_v2(manifest: dict[str, Any]) -> bool:
    """Whether a method package is the one shape this module reads, the same way the trial service
    routes it. A single-good v1 package states no process boundary to cover."""
    output = manifest.get("output_schema") if isinstance(manifest, dict) else None
    return isinstance(output, dict) and output.get("schema_version") == SCHEMA_VERSION


def precursor_membership_coverage_gaps(
    frozen_graph: dict[str, Any], manifest: dict[str, Any]
) -> list[dict[str, str]]:
    """Crossing inputs the package names no membership record for, before anything is solved.

    A project template may rewrite which flow a port carries while the method package keeps its
    Annex I reading pinned to the previous flow identity. Read at solve time that drift costs a
    full engine run; read here it refuses the template.
    """
    package = _check_package(manifest)
    processes = sorted(str(uuid) for uuid in package["multi"]["in_boundary_process_uuids"])
    nodes = _nodes_in_boundary(frozen_graph, processes)
    ports = _enumerate_ports(frozen_graph, nodes)
    categories = _categories(ports, _internal_transfers(frozen_graph, ports, nodes))
    by_flow = _membership_records(manifest)
    return [
        {"exchange_id": exchange_id, "flow_uuid": str(entry["port"].get("flowUuid") or "")}
        for exchange_id, entry in sorted(ports.items())
        if categories[exchange_id] == "crossing"
        and entry["direction"] == "input"
        and str(entry["port"].get("flowUuid") or "") not in by_flow
    ]


def _precursor_decisions(
    ports: dict[str, dict[str, Any]],
    categories: dict[str, str],
    ledger: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    *,
    tri_state: bool,
) -> list[dict[str, Any]]:
    by_flow = {
        flow_uuid: {**entry, **_record_membership(entry, tri_state=tri_state)}
        for flow_uuid, entry in _membership_records(manifest).items()
    }
    decisions: list[dict[str, Any]] = []
    for exchange_id, entry in sorted(ports.items()):
        if categories[exchange_id] != "crossing" or entry["direction"] != "input":
            continue
        flow_uuid = str(entry["port"].get("flowUuid") or "")
        record = by_flow.get(flow_uuid)
        if record is None:
            _fail(
                "CBAM_TRIAL_PRECURSOR_UNDECIDED",
                "a crossing input has no precursor membership evidence, which is not the same "
                "thing as being a non-precursor",
                exchange_id=exchange_id,
                flow_uuid=flow_uuid,
            )
        decision = {
            "exchange_id": exchange_id,
            "flow_uuid": flow_uuid,
            "cn_code": record.get("cn_code"),
            "annex_i_listed": record["annex_i_listed"],
            "clause": record.get("clause"),
            "evidence_ref": record.get("evidence_ref"),
            "gap_ref": record.get("gap_ref"),
        }
        if tri_state:
            membership = str(record["membership"])
            disposition = str(ledger[exchange_id].get("disposition") or "")
            expected = {
                PRECURSOR_DISPOSITION: "listed_precursor",
                INDIRECT_DISPOSITION: "listed_governed_elsewhere",
            }.get(disposition)
            if expected is not None and expected != membership:
                _fail(
                    "CBAM_TRIAL_INDIRECT_ELECTRICITY_PRECURSOR_COLLISION",
                    "one crossing input sits in the precursor term and in the indirect "
                    "electricity term at once, which is the double attribution A-C21 and A-C15 "
                    "forbid on the same flow",
                    exchange_id=exchange_id,
                    flow_uuid=flow_uuid,
                    membership=membership,
                    disposition=disposition,
                )
            if membership == "listed_precursor" and disposition != PRECURSOR_DISPOSITION:
                _fail(
                    "CBAM_TRIAL_COMPONENT_DISPOSITION_CONTRADICTION",
                    "the Annex I reading names this input as a precursor whose mass enters the "
                    "precursor term, while the frozen ledger gives it no precursor disposition",
                    exchange_id=exchange_id,
                    membership=membership,
                    disposition=disposition,
                )
            if membership == "listed_governed_elsewhere" and disposition not in (
                INDIRECT_DISPOSITION,
                "excluded_with_basis",
                NOT_APPLICABLE_DISPOSITION,
            ):
                _fail(
                    "CBAM_TRIAL_COMPONENT_DISPOSITION_CONTRADICTION",
                    "a flow another clause governs was frozen into a term that clause does not "
                    "open for it",
                    exchange_id=exchange_id,
                    membership=membership,
                    disposition=disposition,
                )
            decision["membership"] = membership
            decision["governing_clause"] = record["governing_clause"]
        decisions.append(decision)
    return decisions


def _check_component_buckets(
    *,
    components: dict[str, dict[str, Any]],
    ledger: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """Read one package's Equation 62 terms against one ledger's derived buckets.

    The bucket comes from the disposition, never from a component key a frozen boundary could carry:
    a port's term is a consequence of what it is, so a second label for it could only ever drift.
    """
    sizes = {name: 0 for name in CBAM_COMPONENTS}
    term_of_disposition = {disposition: name for name, disposition in COMPONENT_BUCKETS.items()}
    for entry in ledger.values():
        name = term_of_disposition.get(str(entry.get("disposition") or ""))
        if name is None:
            continue
        sizes[name] += 1
    for name in CBAM_COMPONENTS:
        applicable = components[name]["status"] == "applicable"
        if applicable and sizes[name] == 0:
            _fail(
                "CBAM_TRIAL_COMPONENT_DISPOSITION_CONTRADICTION",
                "the package declares this term of Equation 62 applicable while the frozen "
                "ledger counts no port in its bucket, so the term is declared but never measured",
                component=name,
                status=components[name]["status"],
            )
        if not applicable and sizes[name] > 0:
            _fail(
                "CBAM_TRIAL_COMPONENT_DISPOSITION_CONTRADICTION",
                "the package declares this term of Equation 62 not applicable with a basis, "
                "while the frozen ledger does count ports into its bucket",
                component=name,
                status=components[name]["status"],
                counted=sizes[name],
            )
    return sizes


def _precursor_sources(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rules = manifest.get("precursor_rules") or {}
    sources = rules.get("sources")
    if not isinstance(sources, list) or any(not isinstance(item, dict) for item in sources):
        _fail(
            "CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
            "a three-component package must pin each precursor source as an object",
        )
    attribution = str(rules.get("attribution") or "")
    if attribution not in ("separate_production_process", "joint_production_process"):
        _fail(
            "CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
            "the package declares no closed attribution choice for its precursors",
            attribution=attribution or None,
        )
    seen: set[str] = set()
    for source in sources:
        flow_uuid = str(source.get("flow_uuid") or "")
        if not flow_uuid or flow_uuid in seen:
            _fail(
                "CBAM_TRIAL_DOUBLE_COUNT",
                "one precursor flow is pinned twice by the package, so its mass would enter "
                "the precursor term twice with no order to pick",
                flow_uuid=flow_uuid or None,
            )
        seen.add(flow_uuid)
        for field in (
            "flow_uuid",
            "source_process_uuid",
            "source_seed_id",
            "source_seed_version",
            "method_package_ref",
            "source_package_content_sha256",
            "source_bundle_content_sha256",
            "attribution",
            "clause",
        ):
            if not _non_empty(source.get(field)):
                _fail(
                    "CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
                    "a pinned precursor source states no "
                    f"{field}, so the result One resolves against it has no identity to match",
                    flow_uuid=flow_uuid or None,
                    field=field,
                )
        if "@" not in str(source["method_package_ref"]) or str(
            source["method_package_ref"]
        ).endswith("@latest"):
            _fail(
                "CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
                "a precursor source resolves to a method package version that is not exact",
                flow_uuid=flow_uuid or None,
                method_package_ref=source["method_package_ref"],
            )
    return [{**source} for source in sources]


def _verify_precursor_result(
    result: dict[str, Any],
    *,
    source: dict[str, Any],
    reporting_period: dict[str, Any],
) -> Decimal:
    """Re-run the identity chain the complex-v1 route established, against a v2 result.

    The precursor's specific emissions are only inheritable if the result carrying them is the
    pinned exact package, on the pinned process, for the same period, and passed its own audit.
    """
    flow_uuid = str(source["flow_uuid"])

    def refuse(reason: str, **details: Any) -> None:
        _fail(
            "CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
            reason,
            flow_uuid=flow_uuid,
            method_package_ref=source["method_package_ref"],
            **details,
        )

    if result.get("schema_version") != SCHEMA_VERSION:
        refuse("a three-component precursor must itself be a cbam.trial.v2 result")
    basis = {key: value for key, value in result.items() if key != "content_sha256"}
    if canonical_json_sha256(basis) != result.get("content_sha256"):
        refuse("the precursor result's content hash does not match its own content")
    if result.get("status") not in {"trial_passed", "partial_calculated"}:
        refuse("the precursor result did not pass its own audit")
    method = result.get("method_package") or {}
    if method.get("ref") != source["method_package_ref"]:
        refuse(
            "the precursor result resolves to another method package than the pinned one",
            observed=method.get("ref"),
        )
    if method.get("content_sha256") != source["source_package_content_sha256"]:
        refuse(
            "the precursor result's method package content hash differs from the pinned one",
            observed=method.get("content_sha256"),
        )
    goods = result.get("goods") or {}
    if (goods.get("product_flow") or {}).get("flow_uuid") != flow_uuid:
        refuse(
            "the precursor result produces a different good than the pinned source flow, so the "
            "specific value on it belongs to another commodity",
            observed=(goods.get("product_flow") or {}).get("flow_uuid"),
        )
    if goods.get("production_process_uuid") != source["source_process_uuid"]:
        _fail(
            "CBAM_TRIAL_PRECURSOR_SOURCE_PROCESS_MISMATCH",
            "the precursor's mass and its specific emissions come from different process "
            "identities, which is not one determination restated twice but two determinations",
            flow_uuid=flow_uuid,
            pinned=source["source_process_uuid"],
            observed=goods.get("production_process_uuid"),
        )
    observed_period = result.get("reporting_period") or {}
    for field in ("start_date", "end_date", "resolution"):
        if observed_period.get(field) != reporting_period.get(field):
            _fail(
                "CBAM_TRIAL_PRECURSOR_PERIOD_UNEVIDENCED",
                "the precursor result covers another period than the good that consumes it and "
                "no period evidence record is declared for that difference",
                flow_uuid=flow_uuid,
                field=field,
                pinned=reporting_period.get(field),
                observed=observed_period.get(field),
            )
    specific = result.get("specific_embedded_emissions") or {}
    if specific.get("unit") != RESULT_UNIT:
        refuse(
            "the precursor result states its specific emissions on an unsupported unit",
            observed=specific.get("unit"),
        )
    value = specific.get("partial_value") if result.get("status") == "partial_calculated" else specific.get("value")
    return _decimal(value, field="precursor.specific_embedded_emissions.value")


def _loss_amounts(
    ports: dict[str, dict[str, Any]],
    ledger: dict[str, dict[str, Any]],
    solved_rows: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """Kg lost per precursor source, summed over the loss ports that source names in the package.

    A-C16 counts the precursor on the quantity the process receives, and the cut-off stream is its
    own flow rather than the precursor's, so flow identity cannot make that link and only the
    package can name it. The names are checked against the frozen ledger rather than trusted, and a
    loss port the ledger records that no source claims is refused: it would leave that source's mass
    floor short by its quantity, silently.
    """
    losses: dict[str, Decimal] = {}
    claimed: set[str] = set()
    for source in sorted(sources, key=lambda item: str(item["flow_uuid"])):
        flow_uuid = str(source["flow_uuid"])
        for exchange_id in sorted(str(item) for item in source.get("loss_exchange_ids") or []):
            ledger_entry = ledger.get(exchange_id) or {}
            if exchange_id not in ports or ledger_entry.get("disposition") != LOSS_DISPOSITION:
                _fail(
                    "CBAM_TRIAL_PRECURSOR_LOSS_LINK_UNEVIDENCED",
                    "a precursor source names a loss stream that the frozen ledger does not record "
                    "as a loss of a counted precursor inside this boundary, so its quantity cannot "
                    "be added to that source's mass floor",
                    flow_uuid=flow_uuid,
                    exchange_id=exchange_id,
                )
            claimed.add(exchange_id)
            row = solved_rows.get(exchange_id)
            if row is None:  # a loss port never reaches here unsolved: it is not a zero-value term
                _fail(
                    "CBAM_TRIAL_CANDIDATE_PORT_UNSOLVED",
                    "a loss stream of a counted precursor has no solved exchange, so the total "
                    "demand of that precursor cannot be checked against it",
                    exchange_id=exchange_id,
                )
            losses[flow_uuid] = losses.get(flow_uuid, Decimal("0")) + _decimal(
                row.get("amount"), field=f"scaled_technosphere_exchanges.{exchange_id}.amount"
            )
    unowned = sorted(
        exchange_id
        for exchange_id in ports
        if ledger[exchange_id].get("disposition") == LOSS_DISPOSITION
        and exchange_id not in claimed
    )
    if unowned:
        _fail(
            "CBAM_TRIAL_PRECURSOR_LOSS_STREAM_UNOWNED",
            "the frozen ledger cuts a loss stream off a precursor that no source names, so the "
            "mass floor of that precursor would exclude the quantity the model does not keep",
            exchange_ids=unowned,
        )
    return losses


def _precursor_term(
    *,
    ports: dict[str, dict[str, Any]],
    categories: dict[str, str],
    ledger: dict[str, dict[str, Any]],
    solved_rows: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    precursor_results: list[dict[str, Any]],
    activity_kg: Decimal,
    reporting_period: dict[str, Any],
    in_boundary: list[str],
    nitrogen: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], Decimal, Decimal]:
    """Equation 61/62's precursor term: M_i / AL_g x SEE_i, one row per pinned source flow."""
    sources = _precursor_sources(manifest)
    attribution = str(manifest["precursor_rules"]["attribution"])
    if attribution == "joint_production_process":
        if sources:
            _fail(
                "CBAM_TRIAL_DOUBLE_COUNT",
                "the package attributes its precursors to a joint production process, which "
                "makes their emissions own direct emissions, while still pinning a source result "
                "to add as a precursor term",
                flow_uuids=sorted(str(source["flow_uuid"]) for source in sources),
            )
        return [], Decimal("0"), Decimal("0")
    if not sources:
        _fail(
            "CBAM_TRIAL_PRECURSOR_COUNT_REQUIRED",
            "a complex good whose precursor comes from a separate production process has no "
            "pinned source, so Equation 62's sum has no term to carry those emissions",
        )
    masses: dict[str, Decimal] = {}
    exchanges: dict[str, list[str]] = {}
    for exchange_id, entry in sorted(ports.items()):
        if ledger[exchange_id].get("disposition") != PRECURSOR_DISPOSITION:
            continue
        if categories[exchange_id] != "crossing" or entry["direction"] != "input":
            _fail(
                "CBAM_TRIAL_COMPONENT_DISPOSITION_CONTRADICTION",
                "a precursor mass disposition sits on a port that does not cross the boundary "
                "inbound, so counting its mass would move material that is already inside",
                exchange_id=exchange_id,
                category=categories[exchange_id],
                direction=entry["direction"],
            )
        row = solved_rows.get(exchange_id)
        if row is None:  # unreachable while the disposition is amount-requiring, kept as a fact
            _fail(
                "CBAM_TRIAL_CANDIDATE_PORT_UNSOLVED",
                "a precursor input has no solved exchange, so M_i is missing evidence rather "
                "than a zero",
                exchange_id=exchange_id,
            )
        flow_uuid = str(entry["port"].get("flowUuid") or "")
        masses[flow_uuid] = masses.get(flow_uuid, Decimal("0")) + _decimal(
            row.get("amount"), field=f"scaled_technosphere_exchanges.{exchange_id}.amount"
        )
        exchanges.setdefault(flow_uuid, []).append(exchange_id)
    pinned = [str(source["flow_uuid"]) for source in sources]
    if sorted(pinned) != sorted(set(pinned)):
        _fail(
            "CBAM_TRIAL_DOUBLE_COUNT",
            "the package pins one precursor flow twice",
        )
    uncounted = sorted(set(pinned) - set(masses))
    if uncounted:
        _fail(
            "CBAM_TRIAL_COMPONENT_DISPOSITION_CONTRADICTION",
            "the package pins a precursor source the frozen ledger counts no mass for, so the "
            "term it would carry is declared but never measured",
            flow_uuids=uncounted,
        )
    unpinned = sorted(set(masses) - set(pinned))
    if unpinned:
        _fail(
            "CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
            "the frozen ledger counts precursor mass for a flow the package pins no source for, "
            "so no specific emissions may be inherited for it",
            flow_uuids=unpinned,
        )
    losses = _loss_amounts(ports, ledger, solved_rows, sources)
    by_flow: dict[str, dict[str, Any]] = {}
    for result in precursor_results:
        observed_flow = str(
            ((result.get("goods") or {}).get("product_flow") or {}).get("flow_uuid") or ""
        )
        if not observed_flow or observed_flow in by_flow:
            _fail(
                "CBAM_TRIAL_DOUBLE_COUNT",
                "two precursor source results produce the same good, or one names no product "
                "flow, so a single precursor mass would inherit the same emissions twice",
                flow_uuid=observed_flow or None,
            )
        by_flow[observed_flow] = result
    extra = sorted(set(by_flow) - set(masses))
    if extra:
        _fail(
            "CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
            "a solved precursor result was supplied whose good no precursor term of this "
            "boundary consumes, so it contributes nothing and its presence is a mistake",
            flow_uuids=extra,
        )
    rows: list[dict[str, Any]] = []
    total_tonnes = Decimal("0")
    total_mass = Decimal("0")
    for source in sorted(sources, key=lambda item: str(item["flow_uuid"])):
        flow_uuid = str(source["flow_uuid"])
        result = by_flow.get(flow_uuid)
        if result is None:
            _fail(
                "CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
                "no solved precursor result was supplied for a pinned source flow, and an "
                "inherited specific value may not be replaced by a zero",
                flow_uuid=flow_uuid,
                method_package_ref=source["method_package_ref"],
            )
        see_i = _verify_precursor_result(
            result, source=source, reporting_period=reporting_period
        )
        mass_kg = masses[flow_uuid]
        if source["source_process_uuid"] in in_boundary:
            _fail(
                "CBAM_TRIAL_PRECURSOR_SOURCE_PROCESS_INSIDE_GOODS_PROCESS",
                "the precursor is attributed to a separate production process while its source "
                "process sits inside this good's boundary, which is the A-C10 reading this "
                "attribution excludes",
                flow_uuid=flow_uuid,
                source_process_uuid=source["source_process_uuid"],
            )
        stoichiometric_minimum: Decimal | None = None
        loss_kg = losses.get(flow_uuid)
        if source.get("mass_floor_basis") == "content_of_n_complement":
            if nitrogen is None:
                _fail(
                    "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
                    "a precursor source derives its stoichiometric floor from the complement of "
                    "the nitrogen content while the package declares no nitrogen basis",
                    flow_uuid=flow_uuid,
                )
            content = _decimal(
                nitrogen["content_of_n"]["value"],
                field="nitrogen_basis.content_of_n.value",
            )
            stoichiometric_minimum = activity_kg * (Decimal("1") - content)
            if loss_kg is not None:
                floor = stoichiometric_minimum + loss_kg
                if mass_kg < floor:
                    _fail(
                        "CBAM_TRIAL_PRECURSOR_MASS_STOICHIOMETRIC_WITH_LOSS_OUTPUT",
                        "the precursor mass on this boundary is smaller than the quantity the "
                        "product contains plus the quantity the model cuts off, so the loss "
                        "stream is not inside M_i and A-C16's total demand is not met",
                        flow_uuid=flow_uuid,
                        m_i_kg=str(mass_kg),
                        stoichiometric_minimum_kg=str(stoichiometric_minimum),
                        loss_kg=str(loss_kg),
                    )
                if mass_kg == stoichiometric_minimum:
                    _fail(
                        "CBAM_TRIAL_PRECURSOR_MASS_STOICHIOMETRIC_WITH_LOSS_OUTPUT",
                        "the precursor mass equals the chemical minimum while the model still "
                        "cuts a loss stream off, which is the bare per-tonne coefficient this "
                        "gate exists to refuse",
                        flow_uuid=flow_uuid,
                        m_i_kg=str(mass_kg),
                    )
        m_i = mass_kg / activity_kg
        term = m_i * see_i
        total_tonnes += term
        total_mass += mass_kg
        rows.append(
            {
                "exchange_ids": exchanges[flow_uuid],
                "flow_uuid": flow_uuid,
                "source_process_uuid": source["source_process_uuid"],
                "source_seed": {
                    "seed_id": source["source_seed_id"],
                    "seed_version": source["source_seed_version"],
                    "bundle_content_sha256": source["source_bundle_content_sha256"],
                },
                "method_package_ref": source["method_package_ref"],
                "result_content_sha256": result["content_sha256"],
                "source_coverage_status": "partial" if result.get("status") == "partial_calculated" else "selected_boundary_calculated",
                "source_snapshot": (result.get("source_snapshot") or {}),
                "reporting_period": result.get("reporting_period") or {},
                "attribution": source.get("attribution"),
                "clause": source.get("clause"),
                "M_i": {"value": str(mass_kg), "unit": "kg precursor", "source_unit": "kg"},
                "AL_g": {"value": str(activity_kg), "unit": "kg product"},
                "m_i": {"value": str(m_i), "unit": "t precursor/t product"},
                "SEE_i": {"value": str(see_i), "unit": RESULT_UNIT},
                "m_i_x_SEE_i": {"value": str(term), "unit": RESULT_UNIT},
                "embedded_emissions": {
                    "value": str(term * activity_kg / KG_PER_TONNE),
                    "unit": "t CO2e",
                    "source_value": str(term * activity_kg),
                    "source_unit": "kg CO2e",
                },
                "mass_floor": {
                    "basis": source.get("mass_floor_basis"),
                    "stoichiometric_minimum_kg": (
                        None if stoichiometric_minimum is None else str(stoichiometric_minimum)
                    ),
                    "loss_kg": None if loss_kg is None else str(loss_kg),
                },
            }
        )
    return rows, total_tonnes, total_mass


def _indirect_term(
    *,
    ports: dict[str, dict[str, Any]],
    categories: dict[str, str],
    ledger: dict[str, dict[str, Any]],
    solved_rows: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    components: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """The indirect electricity term's activity, on the unit the ports were solved in.

    No number is produced for this term in this release: Equation 35 needs a versioned grid factor
    package (gap GA-2), and an activity standing in for an emission is the silent zero the closed
    universe exists to refuse.
    """
    accepted = (manifest.get("accepted_units") or {}).get("indirect_electricity_activity")
    if not isinstance(accepted, list) or not accepted or any(
        not _non_empty(entry) for entry in accepted
    ):
        _fail(
            "CBAM_TRIAL_UNIT_CONTRACT_INVALID",
            "a three-component package that counts indirect electricity must state the activity "
            "units it accepts for it",
        )
    expected = (manifest.get("validation_rules") or {}).get("expected_result") or {}
    missing = ((expected.get("components") or {}).get("indirect") or {}).get("missing")
    rows: list[dict[str, Any]] = []
    total = Decimal("0")
    unit: str | None = None
    for exchange_id, entry in sorted(ports.items()):
        if ledger[exchange_id].get("disposition") != INDIRECT_DISPOSITION:
            continue
        if categories[exchange_id] != "crossing" or entry["direction"] != "input":
            _fail(
                "CBAM_TRIAL_COMPONENT_DISPOSITION_CONTRADICTION",
                "an indirect electricity disposition sits on a port that is not a crossing input",
                exchange_id=exchange_id,
                category=categories[exchange_id],
                direction=entry["direction"],
            )
        observed_unit = str(entry["port"].get("unit") or "")
        if not any(
            entry_unit == observed_unit or entry_unit.startswith(f"{observed_unit} ")
            for entry_unit in [str(item) for item in accepted]
        ):
            _fail(
                "CBAM_TRIAL_UNIT_CONTRACT_INVALID",
                "the indirect electricity activity is solved on a unit the package does not "
                "accept, and this release declares no quantity_conversion for it, so turning the "
                "port quantity into that unit would be an undeclared factor",
                exchange_id=exchange_id,
                unit=observed_unit or None,
                accepted=accepted,
            )
        row = solved_rows.get(exchange_id)
        if row is None:  # unreachable while the disposition is amount-requiring, kept as a fact
            _fail(
                "CBAM_TRIAL_CANDIDATE_PORT_UNSOLVED",
                "an indirect electricity input has no solved exchange, so its activity is missing "
                "evidence rather than a zero",
                exchange_id=exchange_id,
            )
        amount = _decimal(
            row.get("amount"), field=f"scaled_technosphere_exchanges.{exchange_id}.amount"
        )
        total += amount
        unit = observed_unit if unit is None else unit
        disposition_entry = ledger[exchange_id]
        rows.append(
            {
                "exchange_id": exchange_id,
                "process_uuid": entry["process_uuid"],
                "activity": {"value": str(amount), "unit": observed_unit},
                "unit_group_identity": {
                    "source_namespace": str(entry["port"].get("flowSourceNamespace")),
                    "unit_group_uuid": str(entry["port"].get("unitGroupUuid")),
                    "unit_group_version": str(entry["port"].get("unitGroupVersion")),
                },
                "emission_factor": None,
                "factor_package_ref": None,
                "factor_period": None,
                "metering_basis": disposition_entry.get("metering_basis"),
                "clause": disposition_entry.get("clause"),
                "basis": disposition_entry.get("basis"),
                "conversion": "none: kept on the unit the port was solved in, per the package's accepted units",
            }
        )
    if rows and not _non_empty(missing):
        _fail(
            "CBAM_TRIAL_INDIRECT_COMPONENT_MISSING",
            "the package counts an indirect electricity term but declares no missing factor "
            "package, so a partial result could not be labelled",
            exchange_ids=[row["exchange_id"] for row in rows],
        )
    return {
        "state": "formula_only" if rows else "not_applicable",
        "value": None,
        "unit": None,
        "activity": None
        if not rows
        else {"value": str(total), "unit": str(unit), "source_unit": str(unit)},
        "emission_factor": None,
        "missing_factor_package": missing if rows else None,
        "clause": components["indirect"]["clause"],
        "exchanges": rows,
        "claim_boundary_note": "activity without a versioned factor package yields no CO2e figure "
        "and no zero in its place",
    }


def _expected_result_check(
    *,
    manifest: dict[str, Any],
    components: dict[str, dict[str, Any]],
    term_values: dict[str, Decimal | None],
    term_units: dict[str, str | None],
    total_unrounded: Decimal,
    partial: bool,
) -> dict[str, Any]:
    """Compare the solved three-term sum against the acceptance-derived declaration.

    The comparison is on unrounded Decimal sums. Quantizing first would turn the 12-decimal
    contract into a false mismatch against the 15-significant-digit value the ledger authors.
    """
    expected = (manifest.get("validation_rules") or {}).get("expected_result")
    if not isinstance(expected, dict):
        _fail(
            "CBAM_TRIAL_PACKAGE_IDENTITY_INCOMPLETE",
            "a three-component package must declare the expected result its terms are checked "
            "against",
        )
    declared_components = expected.get("components")
    if (
        not isinstance(declared_components, dict)
        or sorted(declared_components) != sorted(components)
        or not _non_empty(expected.get("value"))
        or not _non_empty(expected.get("unit"))
        or expected.get("state") not in ("complete", "partial")
    ):
        _fail(
            "CBAM_TRIAL_INDIRECT_COMPONENT_MISSING",
            "the expected result names no value, unit or completion state, or its component set "
            "is not the set of terms the law opens for this good",
            declared=sorted(declared_components)
            if isinstance(declared_components, dict)
            else None,
            required=sorted(components),
        )
    tolerance = _decimal(
        expected.get("tolerance") if expected.get("tolerance") is not None else "0",
        field="expected_result.tolerance",
        allow_zero=True,
    )
    rows: dict[str, Any] = {}
    observed_state = "partial" if partial else "complete"
    for name in CBAM_COMPONENTS:
        declared = declared_components[name]
        if not isinstance(declared, dict) or declared.get("state") not in (
            EXPECTED_COMPONENT_STATES
        ):
            _fail(
                "CBAM_TRIAL_INDIRECT_COMPONENT_MISSING",
                "a declared component of the expected result states no completion state the "
                "runtime can compare against",
                component=name,
            )
        value = term_values[name]
        observed = "complete" if value is not None else str(
            "not_applicable"
            if components[name]["status"] == "not_applicable_with_basis"
            else "formula_only"
        )
        if observed != declared["state"] or observed_state != expected["state"]:
            _fail(
                "CBAM_TRIAL_EXPECTED_TOTAL_MISMATCH",
                "the solved result's completion state is not the state the package declares, "
                "so the two readings disagree about which term makes this result partial",
                component=name,
                declared_component_state=declared["state"],
                observed_component_state=observed,
                declared_total_state=expected["state"],
                observed_total_state=observed_state,
            )
        entry: dict[str, Any] = {
            "state": observed,
            "unit": declared.get("unit"),
            "declared_unit_matches_result_unit": (
                declared.get("unit") == term_units[name]
            ),
            "source": declared.get("source"),
            "expected_value": None if value is None else str(declared.get("value")),
            "actual_value": None if value is None else str(value),
            "deviation_basis": "kg per kg and t per t are the same mass ratio under A-C17, so "
            "this comparison is made on the unrounded sums in that ratio",
        }
        if value is not None:
            declared_value = _decimal(
                declared.get("value"), field=f"expected_result.components.{name}.value"
            )
            entry["absolute_deviation"] = str(abs(value - declared_value))
            entry["within_tolerance"] = abs(value - declared_value) <= tolerance
            if not entry["within_tolerance"]:
                _fail(
                    "CBAM_TRIAL_EXPECTED_TOTAL_MISMATCH",
                    "a solved term of Equation 62 disagrees with the value the acceptance ledger "
                    "authors for it",
                    component=name,
                    expected_value=str(declared_value),
                    actual_value=str(value),
                    tolerance=str(tolerance),
                )
        elif str(declared.get("value")) not in ("None", ""):
            _fail(
                "CBAM_TRIAL_EXPECTED_TOTAL_MISMATCH",
                "a term the runtime carries as formula only or not applicable declares a value "
                "in the expected result, which would make the total incomplete by construction",
                component=name,
                declared_value=declared.get("value"),
            )
        rows[name] = entry
    expected_total = _decimal(expected["value"], field="expected_result.value")
    deviation = abs(total_unrounded - expected_total)
    result = {
        "state": observed_state,
        "expected_total": str(expected_total),
        "actual_total": str(total_unrounded),
        "absolute_deviation": str(deviation),
        "tolerance": str(tolerance),
        "within_tolerance": deviation <= tolerance,
        "unit": expected["unit"],
        "source": expected.get("source"),
        "components": rows,
        "partial_result": partial,
    }
    if not result["within_tolerance"]:
        _fail(
            "CBAM_TRIAL_EXPECTED_TOTAL_MISMATCH",
            "the solved three-term sum disagrees with the total the acceptance ledger authors",
            **{
                key: value
                for key, value in result.items()
                if key not in {"components"}
            },
        )
    return result


def _nitrogen_result(
    *,
    nitrogen: dict[str, Any] | None,
    cn_code: Any,
    total_unrounded: Decimal,
) -> dict[str, Any] | None:
    if nitrogen is None:
        return None
    if nitrogen["composition_adjustment"]["applied"] is True:
        _fail(
            "CBAM_TRIAL_NITROGEN_PARAMETER_UNSOURCED",
            "the package declares A-C23's composition adjustment applied, which needs a measured "
            "composition with its own provenance and reporting period; the runtime authors none, "
            "and an unmeasured range would stand in for one (GA-5)",
        )
    content = _decimal(
        nitrogen["content_of_n"]["value"], field="nitrogen_basis.content_of_n.value"
    )
    parameter = nitrogen["content_of_n"]
    return {
        "applies": True,
        "clause": nitrogen["clause"],
        "legal_denominator": nitrogen["legal_denominator"],
        "value": str(total_unrounded / content),
        "unit": NITROGEN_METRIC,
        "label": nitrogen["labels"]["per_kg_n"],
        "content_of_n": {
            "value": str(parameter["value"]),
            "unit": str(parameter["unit"]),
            "claim_level": str(parameter["claim_level"]),
            "product_form": str(parameter["product_form"]),
            "concentration": parameter.get("concentration"),
            "derivation_route": str(parameter["derivation_route"]),
            "parameter_ref": str(parameter["parameter_ref"]),
            "published_source_sha256": str(parameter["published_source_sha256"]),
        },
        "conversion": CONVERSION_CONTRACT,
        "conversion_note": "the per-kilogram-nitrogen figure is the per-tonne figure divided by "
        "the declared content of nitrogen: t CO2e per t product and kg CO2e per kg product are "
        "the same ratio under A-C17, so content_of_n is the only quantity that scales it and no "
        "coefficient such as 14/7 may stand in for it",
        "composition_adjustment": {
            "applied": False,
            "note": "A-C23's Equation 65/66 rests on a declared composition range, which GA-5 "
            "leaves unresolved for a single-composition product; this field is a unit "
            "conversion of one activity level, not a composition adjustment",
        },
        "per_tonne_product": {
            "value": str(total_unrounded),
            "unit": RESULT_UNIT,
            "label": nitrogen["labels"]["per_tonne_product"],
            "source_field": "specific_embedded_emissions",
        },
        "engineering_indicator_kept_beside": "specific_embedded_emissions",
        "applicable_cn_codes": [str(code) for code in nitrogen["applicable_cn_codes"]],
        "cn_code": cn_code,
    }


def _three_component_checks(
    *,
    coverage_rows: list[dict[str, Any]],
    precursor_decisions: list[dict[str, Any]],
    precursor_rows: list[dict[str, Any]],
    indirect_rows: list[dict[str, Any]],
    ledger: dict[str, dict[str, Any]],
    components: dict[str, dict[str, Any]],
    goods_complexity: Any,
    nitrogen_basis: dict[str, Any] | None,
    specific: dict[str, Any],
) -> dict[str, bool]:
    """The nine §9 checks, each recomputed from the emitted rows rather than asserted.

    A check that read the package's own declaration would pass for a package that declared a term
    it never measured, which is the exact failure this profile exists to refuse.
    """
    term_rows = {
        "direct": [row for row in coverage_rows if row.get("component") == "direct"],
        "indirect": [row for row in coverage_rows if row.get("component") == "indirect"],
        "precursors": [row for row in coverage_rows if row.get("component") == "precursor"],
    }
    arithmetic_holds = True
    recomputed_sum = Decimal("0")
    for row in precursor_rows:
        m_i = _decimal((row.get("m_i") or {}).get("value"), field="precursor.m_i")
        see_i = _decimal((row.get("SEE_i") or {}).get("value"), field="precursor.SEE_i")
        product = _decimal(
            (row.get("m_i_x_SEE_i") or {}).get("value"), field="precursor.m_i_x_SEE_i"
        )
        if m_i * see_i != product:
            arithmetic_holds = False
        recomputed_sum += product
    mass_floor_holds = True
    for row in precursor_rows:
        floor = row.get("mass_floor") or {}
        minimum = floor.get("stoichiometric_minimum_kg")
        if minimum is None:
            continue
        loss_kg = Decimal(str(floor.get("loss_kg") or "0"))
        if _decimal((row.get("M_i") or {}).get("value"), field="precursor.M_i") < (
            _decimal(minimum, field="precursor.mass_floor.stoichiometric_minimum_kg") + loss_kg
        ):
            mass_floor_holds = False
    precursor_exchange_ids = sorted(
        str(exchange_id)
        for exchange_id, entry in ledger.items()
        if entry.get("disposition") == PRECURSOR_DISPOSITION
    )
    row_exchange_ids = sorted(
        exchange_id for row in precursor_rows for exchange_id in row["exchange_ids"]
    )
    indirect_exchange_ids = sorted(str(row["exchange_id"]) for row in indirect_rows)
    complexity_derived = (goods_complexity == "complex") == any(
        str(item.get("membership")) == "listed_precursor" for item in precursor_decisions
    ) and (goods_complexity == "complex") == (
        components.get("precursors", {}).get("status") == "applicable"
    )
    dual_fields = (
        nitrogen_basis is None
        or (
            _non_empty(nitrogen_basis.get("value"))
            and _non_empty(nitrogen_basis.get("unit"))
            and _non_empty(nitrogen_basis.get("label"))
            and _non_empty(
                (nitrogen_basis.get("content_of_n") or {}).get("published_source_sha256")
            )
            and _non_empty((specific.get("value")))
            and _non_empty(specific.get("unit"))
            and specific.get("formula") == THREE_TERM_FORMULA
        )
    )
    emitted_terms = specific.get("terms") or {}
    direct_term_total = (emitted_terms.get("direct") or {}).get("value")
    emitted_precursor_total = (emitted_terms.get("precursors") or {}).get("value")
    precursor_term = (
        Decimal("0")
        if emitted_precursor_total is None
        else _decimal(emitted_precursor_total, field="terms.precursors.value", allow_zero=True)
    )
    sum_holds = (
        direct_term_total is not None
        and str(
            _decimal(direct_term_total, field="terms.direct.value", allow_zero=True)
            + precursor_term
        )
        == str(specific.get("sum_of_terms"))
        and str(recomputed_sum) == str(precursor_term)
    )
    return {
        "every_component_has_clause": all(
            _non_empty(row.get("clause")) for row in coverage_rows
        )
        and all(
            _non_empty(components[name].get("clause"))
            and _non_empty(components[name].get("derivation"))
            and term_rows[name]
            == sorted(term_rows[name], key=lambda row: str(row["exchange_id"]))
            for name in CBAM_COMPONENTS
        ),
        "precursor_membership_state_valid": all(
            str(item.get("membership")) in MEMBERSHIPS for item in precursor_decisions
        )
        and len({str(item["exchange_id"]) for item in precursor_decisions})
        == len(precursor_decisions),
        "goods_complexity_derived_from_membership": complexity_derived,
        "precursor_arithmetic_shown_per_row": arithmetic_holds and sum_holds,
        "precursor_counted_once": row_exchange_ids == precursor_exchange_ids
        and len(row_exchange_ids) == len(set(row_exchange_ids))
        and len({str(row["flow_uuid"]) for row in precursor_rows}) == len(precursor_rows),
        "precursor_mass_includes_losses": mass_floor_holds,
        "indirect_and_precursor_disjoint": not (
            set(indirect_exchange_ids) & set(row_exchange_ids)
        ),
        "nitrogen_basis_sourced_and_dual": dual_fields,
        "precursor_result_identity_pinned": all(
            _non_empty(row.get("result_content_sha256"))
            and "@" in str(row.get("method_package_ref") or "")
            and not str(row.get("method_package_ref") or "").endswith("@latest")
            and _non_empty((row.get("source_snapshot") or {}).get("content_sha256"))
            for row in precursor_rows
        ),
    }


def build_cbam_trial_v2(
    *,
    solved_snapshot_id: str,
    solved_snapshot_sha256: str,
    application_id: str,
    activity_vector: list[dict[str, Any]],
    scaled_technosphere_exchanges: list[dict[str, Any]],
    scaled_elementary_exchanges: list[dict[str, Any]],
    provider_receipt: dict[str, Any],
    frozen_graph: dict[str, Any],
    revision_identity: dict[str, Any],
    boundary: dict[str, Any],
    reporting_period: dict[str, Any],
    end_use_declaration: str | None,
    method_package_ref: str,
    method_package_sha256: str,
    method_package_kind: str,
    method_package_jurisdiction: str | None,
    method_package_valid_from: date | None,
    method_package_valid_to: date | None,
    manifest: dict[str, Any],
    flow_selection: dict[str, Any] | None = None,
    precursor_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if method_package_kind != PACKAGE_KIND:
        _fail(
            "CBAM_TRIAL_METHOD_KIND_MISMATCH",
            "cbam.trial.v2 requires a cbam_trial method package",
        )
    if method_package_jurisdiction != "EU":
        _fail(
            "CBAM_TRIAL_JURISDICTION_MISMATCH",
            "cbam.trial.v2 currently accepts an EU method package only",
        )
    package = _check_package(manifest)
    three_component = bool(package["three_component"])
    components = package["components"]
    nitrogen_package = package["nitrogen"]
    boundary_object = package["multi"]
    in_boundary = sorted(str(uuid) for uuid in boundary_object["in_boundary_process_uuids"])
    product, emission_rules = _check_rules(manifest, in_boundary)
    reference_process = str(boundary_object["reference_process_uuid"])
    if product["process_uuid"] != reference_process:
        _fail(
            "CBAM_TRIAL_BOUNDARY_MISMATCH",
            "the product rule belongs to another process than the boundary's reference process",
            product_process_uuid=product["process_uuid"],
            reference_process_uuid=reference_process,
        )

    year = _calendar_year(reporting_period)
    if year < 2026:
        _fail(
            "CBAM_TRIAL_RULE_PERIOD_UNSUPPORTED",
            "the definitive-period trial does not accept a reporting period before 2026",
        )
    period_start = date(year, 1, 1)
    period_end = date(year, 12, 31)
    if method_package_valid_from and period_start < method_package_valid_from:
        _fail(
            "CBAM_TRIAL_METHOD_NOT_EFFECTIVE",
            "method package is not effective at the start of the reporting period",
        )
    if method_package_valid_to and period_end > method_package_valid_to:
        _fail(
            "CBAM_TRIAL_METHOD_NOT_EFFECTIVE",
            "method package expires before the reporting period ends",
        )
    rule_source = manifest.get("provenance", {}).get("rule_source")
    if not isinstance(rule_source, dict):
        _fail("CBAM_TRIAL_RULE_SOURCE_REQUIRED", "CBAM trial requires a rule source")
    rule_source_hash = _verified_hash(
        rule_source,
        code="CBAM_TRIAL_RULE_SOURCE_HASH_MISMATCH",
        subject="CBAM rule source",
    )

    if str(boundary.get("status") or "") != "frozen" or not _non_empty(boundary.get("frozen_at")):
        _fail(
            "CBAM_TRIAL_BOUNDARY_NOT_FROZEN",
            "cbam.trial.v2 requires a frozen boundary definition",
            status=boundary.get("status"),
        )
    if str(boundary.get("boundary_type") or "") != BOUNDARY_APPLICATION:
        _fail(
            "CBAM_TRIAL_BOUNDARY_NOT_FROZEN",
            "the named boundary belongs to a different application",
            boundary_type=boundary.get("boundary_type"),
            application=BOUNDARY_APPLICATION,
        )
    if str(boundary.get("application_id") or "") != application_id:
        _fail(
            "CBAM_TRIAL_BOUNDARY_NOT_FROZEN",
            "the named boundary belongs to a different application",
            boundary_application_id=boundary.get("application_id"),
            snapshot_application_id=application_id,
        )
    columns = {column: boundary.get(column) for column in BOUNDARY_CONTENT_COLUMNS}
    recorded_hash = str(boundary.get("content_sha256") or "")
    recomputed_hash = canonical_json_sha256(columns)
    if not recorded_hash or recorded_hash != recomputed_hash:
        _fail(
            "CBAM_TRIAL_BOUNDARY_NOT_FROZEN",
            "the boundary row's content hash does not match its own columns",
            boundary_definition_id=boundary.get("id"),
            recorded=recorded_hash or None,
            recomputed=recomputed_hash,
        )
    policy = boundary.get("consolidation_policy") or {}
    for field in ("schema", "reference_process_uuid", "in_boundary_process_uuids", "clause"):
        if policy.get(field) != boundary_object.get(field):
            _fail(
                "CBAM_TRIAL_BOUNDARY_MISMATCH",
                "the method package and the frozen boundary describe different processes",
                field=field,
                method_package=boundary_object.get(field),
                frozen_boundary=policy.get(field),
            )
    if not isinstance(policy.get("coverage_open_items"), list):
        _fail(
            "CBAM_TRIAL_BOUNDARY_MISMATCH",
            "the frozen boundary records no coverage open items to echo",
        )
    pinned_graph_sha256 = str((boundary.get("geographic_scope") or {}).get("graph_sha256") or "")
    # The boundary was frozen against the stored project graph. A purpose-derived calculation model
    # keeps that stored graph as its own separate identity, so the pin is compared against it and
    # never against the derived graph: comparing the derived graph would either refuse every
    # derived answer or accept a boundary that classified another model's universe.
    boundary_model_sha256 = str(
        revision_identity.get("source_graph_sha256")
        or revision_identity.get("graph_sha256")
        or ""
    )
    if pinned_graph_sha256 != boundary_model_sha256:
        _fail(
            "CBAM_TRIAL_BOUNDARY_MISMATCH",
            "the frozen boundary was pinned to another model graph than the one this "
            "snapshot solved, so its dispositions would classify a different universe",
            boundary_pinned=pinned_graph_sha256 or None,
            solved_model=boundary_model_sha256,
            solved_calculation_model=revision_identity.get("graph_sha256"),
        )
    boundary_period_id = boundary.get("period_id")
    if (
        boundary_period_id is not None
        and str(boundary_period_id) != str(reporting_period.get("id"))
    ):
        _fail(
            "CBAM_TRIAL_BOUNDARY_MISMATCH",
            "the frozen boundary was scoped to another reporting period than the one requested, "
            "so its dispositions would be read against a different year",
            boundary_period_id=boundary_period_id,
            requested_period_id=reporting_period.get("id"),
        )
    boundary_package_ref = boundary.get("method_package_ref")
    if boundary_package_ref is not None and str(boundary_package_ref) != str(method_package_ref):
        _fail(
            "CBAM_TRIAL_BOUNDARY_MISMATCH",
            "the frozen boundary names the method package it was frozen for, and this request "
            "names another one, so the dispositions would be read under another calculation",
            boundary_method_package_ref=boundary_package_ref,
            requested_method_package_ref=method_package_ref,
        )

    frozen_model = _frozen_identity(
        frozen_graph=frozen_graph,
        revision_identity=revision_identity,
        provider_receipt=provider_receipt,
    )
    nodes_in_boundary = _nodes_in_boundary(frozen_graph, in_boundary)
    ports = _enumerate_ports(frozen_graph, nodes_in_boundary)
    emission_rules = _identity_selected_rules(manifest, frozen_graph, in_boundary, emission_rules)
    internal = _internal_transfers(frozen_graph, ports, nodes_in_boundary)
    categories = _categories(ports, internal)

    solved_rows: dict[str, dict[str, Any]] = {}
    for row in [*scaled_technosphere_exchanges, *scaled_elementary_exchanges]:
        if not isinstance(row, dict):
            _fail(
                "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                "the solved snapshot holds an exchange that is not an object",
            )
        exchange_id = str(row.get("exchange_id") or "")
        if not exchange_id or exchange_id in solved_rows:
            _fail(
                "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                "a solved exchange id is missing or appears twice in the snapshot",
                exchange_id=exchange_id,
            )
        solved_rows[exchange_id] = row
    for exchange_id in sorted(solved_rows):
        if exchange_id.partition("::")[0] in nodes_in_boundary and exchange_id not in ports:
            _fail(
                "CBAM_TRIAL_FROZEN_MODEL_DRIFT",
                "the solved snapshot carries an exchange the frozen model does not have",
                exchange_id=exchange_id,
                process_id=solved_rows[exchange_id].get("process_id"),
            )

    ledger = _dispositions(boundary)
    selection = _flow_selection(
        flow_selection,
        method_package_ref=method_package_ref,
        method_package_sha256=method_package_sha256,
        declared_counted={str(rule["exchange_id"]) for rule in emission_rules},
        ports=ports,
        ledger=ledger,
    )
    excluded_from_calculation_model: list[str] = []
    for exchange_id in sorted(ledger):
        if exchange_id in ports:
            continue
        # A reviewed exclusion is absent from the calculation model on purpose: the derivation cut it
        # out before the solve, so the boundary that was frozen against the stored model still names
        # it while the model this answer reads does not. Only that one case is tolerated here, and it
        # has to be the reviewed selection's, never a disposition the ledger happens to carry.
        if selection is not None and exchange_id in selection["excluded"]:
            excluded_from_calculation_model.append(exchange_id)
            continue
        _fail(
            "CBAM_TRIAL_CANDIDATE_PORT_UNKNOWN",
            "the frozen boundary classifies an exchange the frozen model does not have",
            exchange_id=exchange_id,
            known=sorted(ports),
        )
    for exchange_id in sorted(ports):
        if exchange_id not in ledger:
            _fail(
                "CBAM_TRIAL_CANDIDATE_PORT_UNCLASSIFIED",
                "a port of the frozen boundary has no recorded disposition",
                exchange_id=exchange_id,
                category=categories[exchange_id],
            )

    elementary_receipts = {
        str(item.get("exchange_id")): item
        for item in provider_receipt.get("elementary_flow_receipts") or []
        if isinstance(item, dict)
    }
    technosphere_receipts = {
        str(item.get("exchange_id")): item
        for item in provider_receipt.get("technosphere_flow_receipts") or []
        if isinstance(item, dict)
    }

    end_use = _resolve_end_use(
        declaration=package["end_use"],
        boundary=boundary,
        request_value=end_use_declaration,
    )
    precursor_decisions = _precursor_decisions(
        ports, categories, ledger, manifest, tri_state=three_component
    )
    if not three_component and precursor_results:
        _fail(
            "CBAM_TRIAL_PRECURSOR_RESULT_NOT_PINNED",
            "a precursor result was supplied for a good whose package declares no precursor "
            "term, so nothing in Equation 62 could ever carry it",
        )

    counted_rules: dict[str, dict[str, Any]] = {}
    for rule in emission_rules:
        exchange_id = str(rule["exchange_id"])
        if rule["greenhouse_gas"] not in package["gases"]:
            _fail(
                "CBAM_TRIAL_GAS_SCOPE_UNSUPPORTED",
                "a counted emission names a gas the method package does not accept",
                exchange_id=exchange_id,
                greenhouse_gas=rule["greenhouse_gas"],
                accepted=package["gases"],
            )
        counted_rules[exchange_id] = rule
    ledger_counted = {
        exchange_id
        for exchange_id, entry in ledger.items()
        if entry.get("disposition") == "counted"
    }
    if ledger_counted != set(counted_rules):
        _fail(
            "CBAM_TRIAL_CLASSIFICATION_INVALID",
            "the method package and the frozen boundary count different exchanges",
            method_package=sorted(counted_rules),
            frozen_boundary=sorted(ledger_counted),
        )

    denominators = sorted(
        exchange_id
        for exchange_id, entry in ledger.items()
        if entry.get("disposition") == DENOMINATOR_DISPOSITION
    )
    if denominators != [product["reference_exchange_id"]]:
        _fail(
            "CBAM_TRIAL_BOUNDARY_MISMATCH",
            "the frozen boundary and the method package disagree on the denominator exchange",
            frozen=denominators,
            method_package=product["reference_exchange_id"],
        )
    reference_exchange_id = str(product["reference_exchange_id"])
    if categories[reference_exchange_id] != "crossing":
        _fail(
            "CBAM_TRIAL_BOUNDARY_MISMATCH",
            "the denominator output is netted inside the boundary or is not technosphere",
            exchange_id=reference_exchange_id,
            category=categories[reference_exchange_id],
        )

    activity_matches = [
        item for item in activity_vector if item.get("process_id") == reference_process
    ]
    if len(activity_matches) != 1:
        _fail(
            "CBAM_TRIAL_ACTIVITY_NOT_UNIQUE",
            "the reference process must resolve once in the activity vector",
            match_count=len(activity_matches),
        )
    activity = activity_matches[0]
    if activity.get("unit") != "kg":
        _fail(
            "CBAM_TRIAL_ACTIVITY_UNIT_MISMATCH",
            "the product Process activity must use kg",
        )
    activity_kg = _decimal(activity.get("value"), field="activity_vector.value")

    precursor_rows: list[dict[str, Any]] = []
    precursor_tonnes = Decimal("0")
    precursor_mass_kg = Decimal("0")
    indirect_term: dict[str, Any] = {}
    if three_component:
        _check_component_buckets(components=components, ledger=ledger)
        precursor_rows, precursor_tonnes, precursor_mass_kg = _precursor_term(
            ports=ports,
            categories=categories,
            ledger=ledger,
            solved_rows=solved_rows,
            manifest=manifest,
            precursor_results=list(precursor_results or []),
            activity_kg=activity_kg,
            reporting_period=reporting_period,
            in_boundary=in_boundary,
            nitrogen=nitrogen_package,
        )
        indirect_term = _indirect_term(
            ports=ports,
            categories=categories,
            ledger=ledger,
            solved_rows=solved_rows,
            manifest=manifest,
            components=components,
        )

    checked_against_frozen: set[str] = set()
    checked_against_receipts: set[str] = set()
    checked_against_solved: set[str] = set()
    product_port = ports[reference_exchange_id]["port"]
    _identity(
        product,
        product_port,
        PORT_FIELDS,
        PORT_KEYS,
        subject="frozen_model",
        exchange_id=reference_exchange_id,
    )
    checked_against_frozen.add(reference_exchange_id)
    product_row = solved_rows.get(reference_exchange_id)
    if product_row is None:
        _fail(
            "CBAM_TRIAL_PRODUCT_EXCHANGE_NOT_UNIQUE",
            "the reference product output is absent from the solved snapshot",
            exchange_id=reference_exchange_id,
        )
    _identity(
        product,
        product_row,
        SOLVED_ROW_FIELDS,
        SOLVED_ROW_KEYS,
        subject="solved_snapshot",
        exchange_id=reference_exchange_id,
    )
    checked_against_solved.add(reference_exchange_id)
    if product_row.get("process_id") != reference_process or product_row.get(
        "exchange_type"
    ) != "technosphere":
        _fail(
            "CBAM_TRIAL_PRODUCT_EXCHANGE_NOT_UNIQUE",
            "the reference product row is not a technosphere exchange of the reference process",
            exchange_id=reference_exchange_id,
        )
    product_kg = _decimal(product_row.get("amount"), field="scaled_product_exchange.amount")
    if product_kg != activity_kg:
        _fail(
            "CBAM_TRIAL_ACTIVITY_PRODUCT_MISMATCH",
            "Process activity and scaled reference-product output differ",
            activity_kg=str(activity_kg),
            product_kg=str(product_kg),
        )
    product_technosphere_receipt = technosphere_receipts.get(reference_exchange_id)
    if product_technosphere_receipt is not None:
        _identity(
            product,
            product_technosphere_receipt,
            TECHNOSPHERE_RECEIPT_FIELDS,
            RECEIPT_KEYS,
            subject="technosphere_receipt",
            exchange_id=reference_exchange_id,
        )

    direct_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    totals_by_kind: dict[str, Decimal] = {}
    source_groups: dict[str, str] = {}
    counted_groups: dict[str, str] = {}
    direct_kg = Decimal("0")
    ports_without_solved_row: list[str] = []
    for exchange_id in sorted(ports):
        entry = ports[exchange_id]
        disposition_entry = ledger[exchange_id]
        disposition = str(disposition_entry.get("disposition") or "")
        if disposition not in DISPOSITIONS:
            _fail(
                "CBAM_TRIAL_CANDIDATE_PORT_UNCLASSIFIED",
                "a port carries a disposition outside the closed set",
                exchange_id=exchange_id,
                disposition=disposition,
            )
        if disposition == "undecided":
            _fail(
                "CBAM_TRIAL_UNDECIDED_REFUSED",
                "a required boundary item is still undecided, so no complete result is returned",
                exchange_id=exchange_id,
                clause=disposition_entry.get("clause"),
            )
        if disposition == PENDING_FACTOR_DISPOSITION:
            pending_rule = (manifest.get('classification_rules', {}).get('pending_activity_rules', {})).get(exchange_id)
            pending_item = next((item for item in policy['coverage_open_items']
                                 if item.get('exchange_id') == exchange_id and item.get('state') == 'missing_data'), None)
            if three_component or not pending_rule or not pending_item or not _non_empty(disposition_entry.get('basis')):
                _fail('CBAM_TRIAL_PENDING_FACTOR_UNDECLARED',
                      'Pending activity needs an exact method rule and disclosed missing-data item in a partial direct component.',
                      exchange_id=exchange_id)
        row = solved_rows.get(exchange_id)
        if row is None:
            if disposition not in ZERO_DISPOSITIONS or not _non_empty(
                disposition_entry.get("basis")
            ):
                _fail(
                    "CBAM_TRIAL_CANDIDATE_PORT_UNSOLVED",
                    "a port of the frozen boundary has no solved exchange, which is missing "
                    "evidence rather than a zero",
                    exchange_id=exchange_id,
                    disposition=disposition,
                )
            ports_without_solved_row.append(exchange_id)
        flow_identity = {
            **{field: entry["port"].get(key) for field, key in PORT_KEYS.items()},
            "compartment": entry["port"].get("compartment"),
        }
        base: dict[str, Any] = {
            "exchange_id": exchange_id,
            "process_uuid": entry["process_uuid"],
            "category": categories[exchange_id],
            "disposition": disposition,
            "clause": disposition_entry.get("clause"),
            "basis": disposition_entry.get("basis"),
            "counterpart": disposition_entry.get("counterpart") or internal.get(exchange_id),
            "amount": None if row is None else str(row.get("amount")),
            "unit": entry["port"].get("unit"),
            "flow_identity": flow_identity,
            "provider_receipt": None,
            "technosphere_receipt": None,
        }
        if three_component:
            base["component"] = COMPONENT_BY_DISPOSITION[disposition]
        if categories[exchange_id] == "internal":
            expected_counterpart = internal.get(exchange_id)
            if base["counterpart"] != expected_counterpart:
                _fail(
                    "CBAM_TRIAL_BOUNDARY_MISMATCH",
                    "an internal transfer names a counterpart the frozen graph does not connect",
                    exchange_id=exchange_id,
                    frozen_boundary=base["counterpart"],
                    frozen_model=expected_counterpart,
                )
        technosphere_receipt = technosphere_receipts.get(exchange_id)
        if technosphere_receipt is not None and categories[exchange_id] != "elementary":
            base["technosphere_receipt"] = {
                key: technosphere_receipt.get(key)
                for key in ("resolution", "content_hash", "snapshot_hash")
            }
        if disposition == "counted":
            rule = counted_rules[exchange_id]
            if categories[exchange_id] != "elementary":
                _fail(
                    "CBAM_TRIAL_CLASSIFICATION_INVALID",
                    "a counted emission must sit on a biosphere port of the frozen model",
                    exchange_id=exchange_id,
                    category=categories[exchange_id],
                )
            _identity(
                rule,
                entry["port"],
                PORT_FIELDS,
                PORT_KEYS,
                subject="frozen_model",
                exchange_id=exchange_id,
            )
            checked_against_frozen.add(exchange_id)
            receipt = elementary_receipts.get(exchange_id)
            if receipt is None:
                _fail(
                    "CBAM_TRIAL_DIRECT_EMISSION_RECEIPT_REQUIRED",
                    "a counted emission has no elementary flow receipt",
                    exchange_id=exchange_id,
                )
            _identity(
                rule,
                receipt,
                TEN_FIELDS,
                RECEIPT_KEYS,
                subject="elementary_receipt",
                exchange_id=exchange_id,
            )
            checked_against_receipts.add(exchange_id)
            content_hash = str(receipt.get("content_hash") or "")
            factor_hash = str(receipt.get("factor_hash") or "")
            if not content_hash or not factor_hash:
                _fail(
                    "CBAM_TRIAL_DIRECT_EMISSION_RECEIPT_REQUIRED",
                    "a counted emission receipt states no dataset or factor hash",
                    exchange_id=exchange_id,
                )
            _identity(
                rule,
                row,
                SOLVED_ROW_FIELDS,
                SOLVED_ROW_KEYS,
                subject="solved_snapshot",
                exchange_id=exchange_id,
            )
            checked_against_solved.add(exchange_id)
            if row.get("process_id") != rule["process_uuid"]:
                _fail(
                    "CBAM_TRIAL_PORT_IDENTITY_DRIFT",
                    "a counted emission's solved row belongs to another process",
                    exchange_id=exchange_id,
                    fields={
                        "process_uuid": {
                            "method_package": rule["process_uuid"],
                            "solved_snapshot": row.get("process_id"),
                        }
                    },
                )
            amount = _decimal(
                row.get("amount"),
                field=f"scaled_elementary_exchanges.{exchange_id}.amount",
                allow_zero=True,
            )
            provider = {
                "content_hash": content_hash,
                "factor_hash": factor_hash,
                "snapshot_hash": receipt.get("snapshot_hash"),
            }
            emission_kind = str(disposition_entry.get("emission_kind") or "unspecified")
            direct_kg += amount
            totals_by_kind[emission_kind] = totals_by_kind.get(emission_kind, Decimal("0")) + amount
            group = disposition_entry.get("source_group")
            if group:
                owner = counted_groups.setdefault(str(group), exchange_id)
                if owner != exchange_id:
                    _fail(
                        "CBAM_TRIAL_DOUBLE_COUNT",
                        "one emission source group is counted at two exchanges",
                        source_group=str(group),
                        exchange_ids=sorted({owner, exchange_id}),
                    )
            direct_rows.append(
                {
                    "exchange_id": exchange_id,
                    "process_uuid": rule["process_uuid"],
                    "emission_kind": emission_kind,
                    "greenhouse_gas": rule["greenhouse_gas"],
                    "flow_identity": {field: rule[field] for field in TEN_FIELDS},
                    "amount": str(amount),
                    "unit": "kg CO2e",
                    "clause": disposition_entry.get("clause"),
                    "basis": disposition_entry.get("basis"),
                    "provider_receipt": provider,
                }
            )
            base["provider_receipt"] = provider
        elif disposition == "excluded_with_basis":
            if not _non_empty(disposition_entry.get("clause")) or not _non_empty(
                disposition_entry.get("basis")
            ):
                _fail(
                    "CBAM_TRIAL_CANDIDATE_PORT_UNCLASSIFIED",
                    "an excluded exchange carries no clause or no basis",
                    exchange_id=exchange_id,
                )
            group = disposition_entry.get("source_group")
            chosen = disposition_entry.get("counted_instead")
            if (group is None) != (chosen is None):
                _fail(
                    "CBAM_TRIAL_DOUBLE_COUNT",
                    "an excluded exchange names half of a single-source choice, so its emission "
                    "source could go missing or be counted twice",
                    exchange_id=exchange_id,
                    source_group=group,
                    counted_instead=chosen,
                )
            if group is not None:
                if str(chosen) == exchange_id or str(chosen) not in counted_rules:
                    _fail(
                        "CBAM_TRIAL_DOUBLE_COUNT",
                        "an excluded exchange points its source at an exchange it is not "
                        "excluded in favour of",
                        exchange_id=exchange_id,
                        counted_instead=str(chosen),
                        source_group=str(group),
                    )
                owner = source_groups.setdefault(str(group), str(chosen))
                if owner != str(chosen):
                    _fail(
                        "CBAM_TRIAL_DOUBLE_COUNT",
                        "one emission source group is attributed to two counted exchanges",
                        source_group=str(group),
                        exchange_ids=sorted({owner, str(chosen)}),
                    )
        coverage_rows.append(base)

    open_items = policy["coverage_open_items"]
    if any(not isinstance(item, dict) for item in open_items):
        _fail(
            "CBAM_TRIAL_BOUNDARY_MISMATCH",
            "the frozen boundary holds a coverage open item that is not an object",
        )
    for group, chosen in sorted(source_groups.items()):
        declared = counted_groups.get(group)
        if declared is not None and declared != chosen:
            _fail(
                "CBAM_TRIAL_DOUBLE_COUNT",
                "a counted exchange and an excluded exchange disagree on which one carries "
                "the source group",
                source_group=group,
                counted=declared,
                counted_instead=chosen,
            )
    crossing_inputs = {
        exchange_id
        for exchange_id, entry in ports.items()
        if categories[exchange_id] == "crossing" and entry["direction"] == "input"
    }
    counted_coverage = {
        row["exchange_id"]: row for row in coverage_rows if row["disposition"] == "counted"
    }
    production_tonnes = activity_kg / KG_PER_TONNE
    direct_tonnes = direct_kg / KG_PER_TONNE
    direct_specific = direct_tonnes / production_tonnes
    total_unrounded = direct_specific + (precursor_tonnes if three_component else Decimal("0"))
    partial_result = three_component and (indirect_term.get("value") is None
        or any(row.get("source_coverage_status") == "partial" for row in precursor_rows))
    specific = total_unrounded.quantize(
        Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
    )

    expected = (manifest.get("validation_rules") or {}).get("expected_direct_emissions_kg")
    cross_check: dict[str, Any]
    if isinstance(expected, dict) and expected.get("value") is not None:
        expected_value = _decimal(expected.get("value"), field="expected_direct_emissions_kg")
        tolerance = _decimal(
            expected.get("tolerance") if expected.get("tolerance") is not None else "0",
            field="expected_direct_emissions_kg.tolerance",
            allow_zero=True,
        )
        deviation = abs(direct_kg - expected_value)
        cross_check = {
            "expected_kg": str(expected_value),
            "actual_kg": str(direct_kg),
            "absolute_deviation": str(deviation),
            "tolerance": str(tolerance),
            "within_tolerance": deviation <= tolerance,
            "source": expected.get("source"),
        }
        if not cross_check["within_tolerance"]:
            _fail(
                "CBAM_TRIAL_EXPECTED_TOTAL_MISMATCH",
                "the solved direct emissions disagree with the expected total the package declares",
                **cross_check,
            )
    else:
        cross_check = {"status": "not_declared_by_method_package"}

    per_process: dict[str, dict[str, Any]] = {
        process_uuid: {
            "process_uuid": process_uuid,
            "engine_node_id": node_id,
            "ports": 0,
            "counted": 0,
            "excluded_with_basis": 0,
            "applicable_pending_factor": 0,
            "not_applicable": 0,
            "undecided": 0,
        }
        for node_id, process_uuid in sorted(
            nodes_in_boundary.items(), key=lambda item: (item[1], item[0])
        )
    }
    for row in coverage_rows:
        counters = per_process[row["process_uuid"]]
        counters["ports"] += 1
        if row["disposition"] == "counted":
            counters["counted"] += 1
        elif row["disposition"] == "excluded_with_basis":
            counters["excluded_with_basis"] += 1
        elif row["disposition"] == PENDING_FACTOR_DISPOSITION:
            counters["applicable_pending_factor"] += 1
        elif row["disposition"] == "undecided":
            counters["undecided"] += 1
        else:
            counters["not_applicable"] += 1

    content = {
        "schema_version": SCHEMA_VERSION,
        "capability_key": CAPABILITY_KEY,
        "method_package": {
            "ref": method_package_ref,
            "content_sha256": method_package_sha256,
            "jurisdiction": method_package_jurisdiction,
            "rule_source_sha256": rule_source_hash,
        },
        "source_snapshot": {
            "id": solved_snapshot_id,
            "content_sha256": solved_snapshot_sha256,
            "application_id": application_id,
        },
        "reporting_period": reporting_period,
        "goods": {
            "cn_code": package["boundary"].get("cn_code"),
            "goods_complexity": package["boundary"].get("goods_complexity"),
            "calculation_scope": package["boundary"].get("calculation_scope"),
            "aggregated_goods_category": package["boundary"].get("aggregated_goods_category"),
            "product_flow": {field: product[field] for field in TEN_FIELDS},
            "production_process_uuid": reference_process,
            "reference_exchange_id": reference_exchange_id,
            "in_boundary_process_uuids": in_boundary,
            "end_use": end_use,
        },
        "activity_level": {
            "value": str(production_tonnes),
            "unit": "t product",
            "source_value": str(activity_kg),
            "source_unit": "kg",
        },
        "attributed_emissions": {
            "direct": {
                "value": str(direct_tonnes),
                "unit": "t CO2e",
                "source_value": str(direct_kg),
                "source_unit": "kg CO2e",
                "exchanges": direct_rows,
            },
            "indirect": None,
            "precursors": [],
        },
        "specific_embedded_emissions": {
            "value": str(specific),
            "unit": "t CO2e/t product",
            "formula": DIRECT_ONLY_FORMULA,
        },
        "coverage": {
            "schema": COVERAGE_SCHEMA,
            "universe_sources": {
                "boundary_definition_id": boundary.get("id"),
                "boundary_name": boundary.get("name"),
                "boundary_content_sha256": recorded_hash,
                "frozen_model": frozen_model,
                "solved_snapshot_id": solved_snapshot_id,
            },
            "processes": list(per_process.values()),
            "exchanges": coverage_rows,
            "totals": {
                "ports": len(ports),
                "counted_kg_co2e": str(direct_kg),
                "by_emission_kind": {
                    kind: str(value) for kind, value in sorted(totals_by_kind.items())
                },
                "unsolved_ports_with_basis": sorted(ports_without_solved_row),
                "cross_checked_with": cross_check,
            },
            "denominator": {
                "reference_process_uuid": reference_process,
                "exchange_id": reference_exchange_id,
                "activity_kg": str(activity_kg),
                "scaled_reference_product_output_kg": str(product_kg),
                "source": "activity_vector_and_scaled_reference_product_output",
                "agreement": activity_kg == product_kg,
            },
            "precursor_membership": precursor_decisions,
            "open_items": open_items,
            "refusals": [],
        },
        "status": "trial_passed",
        "audit": {
            "status": "trial_passed",
            "checks": {
                "candidate_universe_is_closed": len(coverage_rows) == len(ports)
                and len(ledger) == len(ports) + len(excluded_from_calculation_model),
                "every_port_classified_once": all(
                    sum(1 for row in coverage_rows if row["exchange_id"] == exchange_id) == 1
                    for exchange_id in ports
                ),
                "no_silent_zero": all(
                    row["amount"] is not None or row["disposition"] in ZERO_DISPOSITIONS
                    for row in coverage_rows
                )
                and all(
                    row["provider_receipt"] is not None
                    for row in coverage_rows
                    if row["disposition"] == "counted"
                ),
                "multi_process_boundary_declared": set(per_process) == set(in_boundary)
                and sum(counters["ports"] for counters in per_process.values()) == len(ports),
                "double_count_excluded": len(direct_rows)
                == len({row["exchange_id"] for row in direct_rows})
                and len(set(source_groups.values())) == len(source_groups)
                and all(
                    source_groups.get(group) == exchange_id
                    for group, exchange_id in counted_groups.items()
                ),
                "undecided_refused_or_disclosed": all(
                    row["disposition"] != "undecided" for row in coverage_rows
                )
                and all(
                    _non_empty(item.get("clause")) and _non_empty(item.get("item"))
                    for item in open_items
                ),
                "frozen_model_identity_verified": frozen_model["graph_sha256"]
                == frozen_model["recomputed_graph_sha256"]
                and frozen_model["provider_project_id"]
                == frozen_model["upstream_project_id"]
                and str(frozen_model["provider_version"])
                == str(frozen_model["upstream_version"])
                and _non_empty(frozen_model["engine_graph_hash"]),
                "frozen_port_identity_matches_package": checked_against_frozen
                == set(counted_rules) | {reference_exchange_id},
                "solved_row_agrees_on_available_fields": checked_against_solved
                == set(counted_rules) | {reference_exchange_id},
                "elementary_receipt_identity_matches_package": checked_against_receipts
                == set(counted_rules),
                "activity_matches_scaled_reference_product": activity_kg == product_kg,
                "precursor_membership_decided_for_every_input": {
                    item["exchange_id"] for item in precursor_decisions
                }
                == crossing_inputs,
                "no_default_values_used": True,
                "no_lcia_factor_recalculation": True,
            },
            "not_checked": {
                "provider_boundary_role_label": (
                    "One drops provider boundary_role when it persists solved rows, so v2 "
                    "classifies ports from the frozen graph edges instead"
                ),
                "technosphere_receipt_coverage": {
                    "exchange_ids": sorted(technosphere_receipts),
                    "counted_exchange_ids_missing_receipt": sorted(
                        set(counted_coverage) - set(technosphere_receipts)
                    ),
                },
            },
            "limitations": package["limitations"],
        },
        "claim_boundary": {
            "trial_only": True,
            "not_a_cbam_declaration": True,
            "not_verified_embedded_emissions": True,
            "certificate_liability_not_calculated": True,
            "carbon_price_deduction_not_calculated": True,
            "free_allocation_adjustment_not_calculated": True,
        },
    }
    if selection is not None:
        # The report carries the counted set itself, so an export or a reader downstream filters by
        # this record instead of resolving a list of its own from the method package. A trial with no
        # reviewed selection keeps the bytes it published before exchanges could be classified.
        content["coverage"]["flow_selection"] = {
            "schema_version": FLOW_SELECTION_SCHEMA,
            "method_package": selection["method_package"],
            "manifest_path": selection["manifest_path"],
            "included_exchange_ids": sorted(selection["included"]),
            "excluded_exchange_ids": sorted(selection["excluded"]),
            "decisions": selection["decisions"],
            "excluded_exchange_ids_absent_from_calculation_model": excluded_from_calculation_model,
        }
        content["audit"]["checks"][
            "counted_exchanges_are_the_reviewed_selection"
        ] = set(counted_rules) == selection["included"]
    if three_component:
        term_values: dict[str, Decimal | None] = {
            "direct": direct_specific,
            "indirect": None
            if indirect_term.get("value") is None
            else _decimal(indirect_term["value"], field="indirect_emissions.value"),
            "precursors": precursor_tonnes if precursor_rows else None,
        }
        term_units = {
            "direct": RESULT_UNIT,
            "indirect": (indirect_term.get("activity") or {}).get("unit"),
            "precursors": RESULT_UNIT if precursor_rows else None,
        }
        content["nitrogen_basis"] = _nitrogen_result(
            nitrogen=nitrogen_package,
            cn_code=package["boundary"].get("cn_code"),
            total_unrounded=total_unrounded,
        )
        content["attributed_emissions"]["indirect"] = indirect_term
        content["attributed_emissions"]["precursors"] = precursor_rows
        content["specific_embedded_emissions"].update(
            {
                "formula": THREE_TERM_FORMULA,
                "sum_of_terms": str(total_unrounded),
                "partial_result": partial_result,
                "terms": {
                    name: {
                        "clause": components[name]["clause"],
                        "derivation": components[name]["derivation"],
                        "value": None
                        if term_values[name] is None
                        else str(term_values[name]),
                        "unit": term_units[name],
                        "state": str(
                            {
                                "direct": "complete",
                                "indirect": indirect_term.get("state") or "not_applicable",
                                "precursors": "complete" if precursor_rows else "not_applicable",
                            }[name]
                        ),
                        "missing_factor_package": (
                            indirect_term.get("missing_factor_package")
                            if name == "indirect"
                            else None
                        ),
                    }
                    for name in CBAM_COMPONENTS
                },
            }
        )
        content["coverage"].update(
            {
                "precursors": precursor_rows,
                "indirect": indirect_term.get("exchanges") or [],
            }
        )
        content["coverage"]["totals"].update(
            {
                "precursor_mass_kg": str(precursor_mass_kg),
                "indirect_activity": indirect_term.get("activity"),
                "expected_result_checked_with": _expected_result_check(
                    manifest=manifest,
                    components=components,
                    term_values=term_values,
                    term_units=term_units,
                    total_unrounded=total_unrounded,
                    partial=partial_result,
                ),
            }
        )
        content["audit"]["checks"].update(_three_component_checks(
            coverage_rows=coverage_rows,
            precursor_decisions=precursor_decisions,
            precursor_rows=precursor_rows,
            indirect_rows=indirect_term.get("exchanges") or [],
            ledger=ledger,
            components=components,
            goods_complexity=package["boundary"].get("goods_complexity"),
            nitrogen_basis=content["nitrogen_basis"],
            specific=content["specific_embedded_emissions"],
        ))

    # Port classification is a technical check, not evidence that all required
    # source streams are represented by the model. Keep the subtotal available
    # while withholding the complete value whenever coverage remains open.
    incomplete = bool(open_items) or bool(
        content["specific_embedded_emissions"].get("partial_result")
    )
    content["claim_boundary"].update({
        "complete_cbam_total": False,
        "verification_status": "not_verified",
        "declaration_available": False,
        "coverage_status": "partial" if incomplete else "selected_boundary_calculated",
        "data_period_coverage": "not_established_by_solved_snapshot",
        "no_conservative_upper_bound_claim": True,
    })
    if incomplete:
        specific_result = content["specific_embedded_emissions"]
        specific_result["partial_value"] = specific_result["value"]
        specific_result["value"] = None
        specific_result["partial_result"] = True
        specific_result["status"] = "incomplete"
        content["status"] = "partial_calculated"
        content["audit"]["status"] = "technical_checks_passed"
        content["audit"]["checks_scope"] = "declared_ports_only_not_regulatory_completeness"
    return {**content, "content_sha256": canonical_json_sha256(content)}
