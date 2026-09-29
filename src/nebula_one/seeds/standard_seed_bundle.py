"""Build and self-check a standard LCA seed engine bundle.

The authorable files under cases/standard-lca-seeds/<seed>/ are the source of truth. This
module only reads them, runs the contract checks the seed promises, and writes build/.
It never contacts an engine: content identity is the bundle digest it computes, while the
engine's own graph hash is recorded later by the install receipt. The install service runs
the same gates in process, so a seed that cannot pass here never reaches an engine.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import zipfile
from contextlib import contextmanager
from decimal import Decimal, localcontext
from functools import wraps
from pathlib import Path, PurePosixPath

from ..analysis.cbam_trial_v2 import BOUNDARY_SCHEMA as MULTI_PROCESS_BOUNDARY_SCHEMA
from ..analysis.cbam_trial_v2 import PORT_KEYS
from ..analysis.cbam_trial_v2 import SCHEMA_VERSION as CBAM_TRIAL_V2_SCHEMA
from ..hashing import canonical_json_sha256
from ..runtime_schemas import MethodPackageCreate


def _repo_root() -> Path:
    source_root = Path(__file__).resolve().parents[3]
    if (source_root / "cases").is_dir():
        return source_root
    casepack_roots = os.getenv("NEBULA_ONE_CASEPACK_ROOTS", "")
    for configured in casepack_roots.split(os.pathsep):
        root = Path(configured.strip())
        if root.name == "cases" and root.is_dir():
            return root.parent
    return source_root


REPO_ROOT = _repo_root()
DECIMAL_PRECISION = 25
BUNDLE_SCHEMA = "nebula.project.bundle.v1"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_FILES = 32
ZIP_TIMESTAMP = (2026, 9, 18, 0, 0, 0)
TOLERANCE = Decimal("0.000001")
REQUIRED_ENTRIES = (
    "project.json",
    "versions.json",
    "runs.json",
    "catalog/flows.json",
    "catalog/flow_versions.json",
    "catalog/unit_groups.json",
    "catalog/unit_definitions.json",
    "dependencies.json",
)
SCALAR_PINS = (
    "graph_sha256",
    "roles_sha256",
    "flow_dependencies_sha256",
    "owned_flows_sha256",
    "project_row_sha256",
    "acceptance_sha256",
    "clause_mapping_sha256",
    "bundle_content_sha256",
)
GROUP_PINS = ("parameters_sha256", "boundaries_sha256")
# a seed declares which authored files feed which check instead of the checks naming them
PROFILE_MAP_FIELDS = ("parameter_files",)
PROFILE_LIST_FIELDS = ("boundary_files", "arithmetic_checks")
PARAMETER_PATH_PREFIX = "parameters/"
ARITHMETIC_CHECKS = {
    "stoichiometry": {"stoichiometry": ("atomic_weights", "molar_masses", "reactions", "derived_coefficients")},
    "combustion": {
        "factor": ("normalized_quantities", "as_published"),
        "oxidation": ("value",),
        "activities": ("slots",),
    },
    "mfa_expectations": {},
    # the three checks below are the seed-declared generalisation of the two above: no exchange id,
    # species name or activity figure of one seed appears in them, so a second seed can bind them
    "stoichiometric_demand": {
        "stoichiometry": ("atomic_weights", "molar_masses", "reactions", "precursor_demand"),
        "loss": ("losses",),
    },
    "fuel_combustion_coverage": {
        "factor": ("normalized_quantities", "as_published"),
        "oxidation": ("value",),
        "activities": ("slots",),
    },
    "mass_balance": {},
    "result_expectations": {},
    "nitrogen_basis": {
        "stoichiometry": ("atomic_weights", "molar_masses"),
        "nitrogen": ("value", "claim_level", "derivation", "published_source"),
    },
}
CLAUSE_ID_SHAPE = re.compile(r"(.*?)(\d+)")
BOUNDARY_CONCLUSIONS = (
    "included",
    "included_with_clause_basis",
    "counted_with_clause_basis",
    "excluded_with_clause_basis",
    "coverage_limit",
    "undecided",
    "reported_separately_not_mass",
    "counted_indirect_with_clause_basis",
)
# Annex I membership of a boundary-crossing input: listed and counted as a precursor, listed but
# governed by another clause (electricity), or absent from the Annex I goods list altogether
PRECURSOR_MEMBERSHIPS = ("listed_precursor", "listed_governed_elsewhere", "not_listed")
PRECURSOR_ATTRIBUTIONS = ("joint_production_process", "separate_production_process")
# the one conclusion whose included_exchanges are counted as precursor mass rather than as CO2
PRECURSOR_CONCLUSION = "counted_with_clause_basis"
# consumed electricity attributed through the indirect rules: counted, but never as CO2 of this
# boundary, so it must not share the bucket a direct emission is reported in
INDIRECT_CONCLUSION = "counted_indirect_with_clause_basis"
NON_DIRECT_CONCLUSIONS = (PRECURSOR_CONCLUSION, INDIRECT_CONCLUSION)
# the frozen disposition a segment conclusion produces; the runtime gains the two new values in the
# next slice, and refuses any disposition it does not know, so the ledger may be segmented first
COUNTED_DISPOSITION = "counted"
PRECURSOR_DISPOSITION = "precursor_mass_counted"
INDIRECT_DISPOSITION = "indirect_electricity_counted"
LOSS_DISPOSITION = "loss_stream_of_an_already_counted_precursor"
# the two calculation profiles a v2 CBAM package may restate, and the components of the second one
CBAM_CALCULATIONS = (
    "actual_specific_embedded_emissions_multi_process_direct_only",
    "actual_specific_embedded_emissions_multi_process_three_component",
)
CBAM_THREE_COMPONENT_CALCULATION = CBAM_CALCULATIONS[1]
CBAM_COMPONENTS = ("direct", "indirect", "precursors")
CBAM_COMPONENT_STATUSES = ("applicable", "not_applicable_with_basis")
CBAM_COMPONENT_BUCKETS = {"direct": "counted", "indirect": "indirect", "precursors": "precursor"}
CBAM_EXPECTED_COMPONENT_STATES = ("complete", "formula_only", "not_applicable")
NO_RUNTIME_DECLARATION_STATE = "no_runtime_declaration_for_this_good"
# a precursor source is only pinned if it names one release of one seed, so an id@x.y.z shape is the
# machine check that no result is ever resolved to "latest"
EXACT_PACKAGE_REF = re.compile(r"^[A-Za-z0-9._-]+@\d+\.\d+\.\d+$")
# acceptance ledger key -> method package key for one pinned precursor source
SOURCE_PIN_FIELDS = {
    "seed_id": "source_seed_id",
    "seed_version": "source_seed_version",
    "seed_directory": "source_seed_directory",
    "package_ref": "method_package_ref",
    "package_content_sha256": "source_package_content_sha256",
    "bundle_content_sha256": "source_bundle_content_sha256",
}
CROSS_SEED_NAMESPACE = "nebula.standard-lca-seed"
LOSS_BASIS = ("share_of_fed_mass", "absolute_quantity")
NITROGEN_CLAIM_LEVELS = ("measured", "derived_stoichiometric")
PRODUCT_FORMS = ("anhydrous", "hydrous_solution")
# the package copy of the parameter record that the builder compares field by field, because a
# runtime can only read what the package carries
NITROGEN_CONTENT_FIELDS = ("value", "unit", "claim_level", "product_form", "concentration")
# the closed set of bases a pinned precursor's stoichiometric mass floor may derive from
MASS_FLOOR_BASES = ("content_of_n_complement",)
COMPONENT_KINDS = ("direct_co2", "precursor_mass", "indirect_electricity")
CBAM_PACKAGE_KIND = "cbam_trial"
METHOD_PACKAGE_DIR = "methods"
PACKAGE_IDENTITY_FIELDS = ("package_id", "version", "package_kind")
ELEMENTARY_PORT_IDENTITY_FIELDS = (
    "flowSourceNamespace",
    "flowVersion",
    "flowPropertyUuid",
    "flowPropertyVersion",
)
TECHNOSPHERE_PORT_IDENTITY_FIELDS = (
    "flowSourceNamespace",
    "flowVersion",
    "flowPropertyUuid",
    "flowPropertyVersion",
    "unitGroupUuid",
    "unitGroupVersion",
)
TECHNOSPHERE_BASIS_TO_PORT = {
    "flow_property_uuid": "flowPropertyUuid",
    "flow_property_version": "flowPropertyVersion",
    "unit_group_uuid": "unitGroupUuid",
    "unit_group_version": "unitGroupVersion",
    "unit": "unit",
}
TECHNOSPHERE_BASIS_REQUIRED_FIELDS = (
    "flow_property_uuid",
    "flow_property_version",
    "unit_group_uuid",
    "unit_group_version",
    "unit",
    "provenance",
    "attestable_on_current_engine",
)
ELEMENTARY_REF_REQUIRED_FIELDS = (
    "exchange_id",
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
ELEMENTARY_REF_TO_PORT = {
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
ATOMS = {
    "CH4": {"C": 1, "H": 4},
    "H2O": {"H": 2, "O": 1},
    "CO": {"C": 1, "O": 1},
    "CO2": {"C": 1, "O": 2},
    "H2": {"H": 2},
    "O2": {"O": 2},
}


class BuildError(Exception):
    pass


class Amounts(dict):
    """A missing exchange is a refusal that names the item, never a KeyError."""

    def __init__(self, mapping=(), *, missing_code: str = "GRAPH_EXCHANGE_MISSING") -> None:
        super().__init__(mapping)
        self.missing_code = missing_code

    def __missing__(self, key: str) -> Decimal:
        raise BuildError(f"{self.missing_code} {key}")


@contextmanager
def arithmetic_environment():
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        yield


def pinned_arithmetic(method):
    # the acceptance table documents precision 25; mutating the process global context would leak into any importer
    @wraps(method)
    def wrapper(*args, **kwargs):
        with arithmetic_environment():
            return method(*args, **kwargs)

    return wrapper


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dec(value: object) -> Decimal:
    return Decimal(str(value))


def close(left: Decimal, right: Decimal) -> bool:
    if left == right:
        return True
    scale = max(abs(left), abs(right))
    return bool(scale) and abs(left - right) / scale <= TOLERANCE


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def parse_equation(
    equation: str, known: dict[str, dict] | None = None
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    species_known = ATOMS if known is None else known
    sides = equation.split("->")
    if len(sides) != 2:
        raise BuildError(f"EQUATION_UNPARSEABLE {equation}")
    parsed: list[dict[str, Decimal]] = []
    for side in sides:
        species: dict[str, Decimal] = {}
        for term in side.split("+"):
            term = term.strip()
            match = re.fullmatch(r"(?:(\d+)\s*)?([A-Za-z0-9]+)", term)
            if match is None:
                raise BuildError(f"EQUATION_TERM_UNPARSEABLE {term}")
            count, name = match.groups()
            if name not in species_known:
                raise BuildError(f"EQUATION_SPECIES_UNKNOWN {name}")
            species[name] = species.get(name, Decimal(0)) + dec(count or 1)
        parsed.append(species)
    return parsed[0], parsed[1]


def element_totals(
    side: dict[str, Decimal], composition: dict[str, dict] | None = None
) -> dict[str, Decimal]:
    species_atoms = ATOMS if composition is None else composition
    totals: dict[str, Decimal] = {}
    for species, count in side.items():
        for element, number in species_atoms[species].items():
            totals[element] = totals.get(element, Decimal(0)) + count * number
    return totals


FORMULA_TERM = re.compile(r"(?:(\d+)\s*)?([A-Za-z]{1,2})")


def parse_formula(formula: str, weights: dict[str, Decimal]) -> dict[str, Decimal]:
    """Read a declared composition such as ``N + 3 H`` instead of a builder constant."""
    composition: dict[str, Decimal] = {}
    for term in formula.split("+"):
        match = FORMULA_TERM.fullmatch(term.strip())
        if match is None:
            raise BuildError(f"FORMULA_TERM_UNPARSEABLE {formula}")
        count, element = match.groups()
        if element not in weights:
            raise BuildError(f"FORMULA_ELEMENT_UNKNOWN {formula} {element}")
        composition[element] = composition.get(element, Decimal(0)) + dec(count or 1)
    if not composition:
        raise BuildError(f"FORMULA_EMPTY {formula}")
    return composition


def side_mass(side: dict[str, Decimal], masses: dict[str, Decimal]) -> Decimal:
    return sum((count * masses[species] for species, count in side.items()), Decimal(0))


def relative_to_repo(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


class SeedBuild:
    def __init__(self, seed_dir: Path) -> None:
        self.dir = seed_dir
        self.manifest = self.read("seed.json")
        self.clause_mapping = self.read("eu-clause-mapping.json")
        self.roles = self.read("model/roles.json")
        self.graph_document = self.read("model/graph.json")
        self.flow_dependencies = self.read("model/flow-dependencies.json")
        self.owned_flows = self.read("model/owned-flows.json")
        self.project_row = self.read("model/project-row.json")
        self.profile = self.check_profile()
        self.parameters = {
            role: self.read(self.profile["parameter_files"][role])
            for role in sorted(self.profile["parameter_files"])
        }
        self.boundaries = {
            name: self.read(f"boundaries/{name}.json") for name in self.profile["boundary_files"]
        }
        self.clause_pattern = self.derive_clause_pattern()
        self.expected = self.read("acceptance/expected-values.json")
        self.graph = self.graph_document["graph"]
        self.seed_id = self.manifest["seed_id"]
        self.version = self.manifest["version"]
        self.identity = self.manifest["identity"]
        self._method_packages: dict[str, dict] | None = None
        self._documents: dict[Path, dict] = {}

    def check_profile(self) -> dict:
        """Validate the seed's own declaration of which files feed which check."""
        profile = self.manifest.get("seed_profile")
        if not isinstance(profile, dict):
            raise BuildError("SEED_PROFILE_MISSING")
        for field in PROFILE_MAP_FIELDS + PROFILE_LIST_FIELDS:
            value = profile.get(field)
            if field in PROFILE_LIST_FIELDS:
                declared = isinstance(value, list) and all(
                    isinstance(item, str) and item for item in value
                )
            else:
                declared = isinstance(value, dict) and all(
                    isinstance(path, str) and path for path in value.values()
                )
            if not declared:
                raise BuildError(f"SEED_PROFILE_FIELD_INVALID {field}")
        for field in PROFILE_LIST_FIELDS:
            listed = profile[field]
            duplicated = sorted({item for item in listed if listed.count(item) > 1})
            if duplicated:
                raise BuildError(f"SEED_PROFILE_ENTRY_DUPLICATED {field} {duplicated}")
        files = profile["parameter_files"]
        if any(not path.startswith(PARAMETER_PATH_PREFIX) for path in files.values()):
            raise BuildError("SEED_PROFILE_PARAMETER_PATH")
        if "cbam" not in profile["boundary_files"]:
            raise BuildError("SEED_PROFILE_BOUNDARY_MISSING cbam")
        for check in profile["arithmetic_checks"]:
            if check not in ARITHMETIC_CHECKS or not callable(
                getattr(self, f"check_{check}", None)
            ):
                raise BuildError(f"SEED_PROFILE_CHECK_UNKNOWN {check}")
            unused = [role for role in ARITHMETIC_CHECKS[check] if role not in files]
            if unused:
                raise BuildError(f"SEED_PROFILE_PARAMETER_MISSING {check} {sorted(unused)}")
        # the pins hash these two folders, so an authored file the profile never names would be
        # part of the seed identity while no check ever reads it
        declared = set(files.values())
        declared |= {f"boundaries/{name}.json" for name in profile["boundary_files"]}
        shipped = {
            path.relative_to(self.dir).as_posix()
            for folder in ("parameters", "boundaries")
            for path in (self.dir / folder).glob("*.json")
        }
        if unread := sorted(shipped - declared):
            raise BuildError(f"SEED_PROFILE_FILE_UNREAD {unread}")
        return profile

    def derive_clause_pattern(self) -> re.Pattern[str]:
        ids = [str(clause.get("id") or "") for clause in self.clause_mapping["clauses"]]
        if not ids:
            raise BuildError("CLAUSE_TABLE_EMPTY")
        split = [CLAUSE_ID_SHAPE.fullmatch(item) for item in ids]
        if any(row is None or not row.group(1) for row in split):
            raise BuildError(
                f"CLAUSE_ID_UNPARSEABLE {[i for i, r in zip(ids, split) if r is None or not r.group(1)]}"
            )
        prefixes = {row.group(1) for row in split}
        widths = {len(row.group(2)) for row in split}
        if len(prefixes) != 1:
            raise BuildError(f"CLAUSE_ID_PREFIX_AMBIGUOUS {sorted(prefixes)}")
        if len(widths) != 1:
            raise BuildError(f"CLAUSE_ID_WIDTH_AMBIGUOUS {sorted(widths)}")
        return re.compile(re.escape(next(iter(prefixes))) + r"\d{%d}(?!\d)" % next(iter(widths)))

    def read(self, relative: str) -> dict:
        path = self.dir / relative
        if not path.is_file():
            raise BuildError(f"MISSING_AUTHORABLE_FILE {relative}")
        return json.loads(path.read_text(encoding="utf-8"))

    # ---------- identity layer ----------

    def check_identity(self) -> None:
        namespace = uuid.uuid5(uuid.NAMESPACE_DNS, "nebula-one.dev/standard-lca-seed/instance/v1")
        if self.identity["namespace"] != str(namespace):
            raise BuildError(f"IDENTITY_NAMESPACE_MISMATCH {self.identity['namespace']} != {namespace}")
        revision = self.identity["revision"]
        derived = {
            "project_id": uuid.uuid5(namespace, f"project|{self.seed_id}|{self.version}"),
            "model_version_id": uuid.uuid5(namespace, f"version|{self.seed_id}|{self.version}|{revision}"),
        }
        for role_id, pinned in self.identity["process_uuids"].items():
            derived[f"process/{role_id}"] = uuid.uuid5(namespace, f"process|{self.seed_id}|{self.version}|{role_id}")
        keys = self.owned_flows["identity_keys"]
        names = [row["flow_name"] for row in self.owned_flows["rows"]]
        if len(keys) != len(names):
            raise BuildError("OWNED_FLOW_KEY_COUNT")
        if len(set(names)) != len(names) or len(set(keys)) != len(keys):
            raise BuildError("OWNED_FLOW_NAME_COLLISION")
        for index, key in enumerate(keys):
            derived[f"flow/{key}"] = uuid.uuid5(namespace, f"flow|{self.seed_id}|{self.version}|{key}")
            if self.owned_flows["rows"][index]["flow_uuid"] != str(derived[f"flow/{key}"]):
                raise BuildError(f"IDENTITY_MISMATCH flow/{key} row={self.owned_flows['rows'][index]['flow_uuid']}")
            if self.identity["owned_flow_uuids"].get(key) != str(derived[f"flow/{key}"]):
                raise BuildError(f"IDENTITY_MISMATCH flow/{key} manifest")
        for name, value in derived.items():
            pinned = self.identity.get(name) or next(
                (role["process_uuid"] for role in self.roles["roles"] if f"process/{role['role_id']}" == name), None
            )
            if pinned is not None and pinned != str(value):
                raise BuildError(f"IDENTITY_MISMATCH {name} pinned={pinned} derived={value}")
        if self.project_row["payload"]["id"] != self.identity["project_id"]:
            raise BuildError("PROJECT_ROW_IDENTITY_MISMATCH")
        if self.identity["revision"] != self.graph_document["revision"]:
            raise BuildError("REVISION_MISMATCH")
        for node in self.graph["nodes"]:
            if node["process_uuid"] != self.identity["process_uuids"].get(node["id"]):
                raise BuildError(f"GRAPH_PROCESS_IDENTITY_MISMATCH {node['id']}")
        for port in self.graph_ports():
            if port.get("flowSourceNamespace") == CROSS_SEED_NAMESPACE:
                if self.owned_flow_name_by_uuid(port["flowUuid"]) is None:
                    if self.cross_seed_dependency_row(port) is None:
                        raise BuildError(f"OWNED_FLOW_UNDECLARED {port['flowUuid']}")

    def cross_seed_dependency_row(self, port: dict) -> dict | None:
        """A seed-owned namespace is not proof this seed published the row: a second seed may
        reuse the first one's catalog flow, which only a verify_present dependency row names."""
        for row in self.flow_dependencies["dependencies"]:
            if row["disposition"] != "verify_present" or row["flow_uuid"] != port["flowUuid"]:
                continue
            observed = row.get("observed") or {}
            if observed.get("source_namespace") == port.get(
                "flowSourceNamespace"
            ) and observed.get("source_version") == port.get("flowVersion"):
                return row
        return None

    def owned_flow_name_by_uuid(self, flow_uuid: str) -> str | None:
        for key, pinned in self.identity["owned_flow_uuids"].items():
            if pinned == flow_uuid:
                return key
        return None

    def graph_ports(self) -> list[dict]:
        ports = []
        for node in self.graph["nodes"]:
            for port in node["inputs"] + node["outputs"]:
                enriched = dict(port)
                enriched["_exchange_id"] = f'{node["id"]}::{port["id"]}'
                ports.append(enriched)
        return ports

    # ---------- parameter layer ----------

    def check_parameter_shapes(self) -> None:
        """A profile that points a check at the wrong file refuses, it does not raise KeyError."""
        for check in self.profile["arithmetic_checks"]:
            for role, keys in sorted(ARITHMETIC_CHECKS[check].items()):
                missing = [key for key in keys if key not in self.parameters[role]]
                if missing:
                    raise BuildError(f"SEED_PROFILE_PARAMETER_SHAPE {check}/{role} {missing}")

    def atomic_weights(self) -> dict[str, Decimal]:
        return {row["element"]: dec(row["value"]) for row in self.parameters["stoichiometry"]["atomic_weights"]}

    def molar_masses(self) -> dict[str, Decimal]:
        return {row["species"]: dec(row["value"]) for row in self.parameters["stoichiometry"]["molar_masses"]}

    def check_stoichiometry(self) -> None:
        atoms = self.atomic_weights()
        masses = self.molar_masses()
        for species, composition in ATOMS.items():
            total = sum(atoms[element] * count for element, count in composition.items())
            if masses[species] != total:
                raise BuildError(f"MOLAR_MASS_MISMATCH {species} table={masses[species]} atoms={total}")
        for reaction in self.parameters["stoichiometry"]["reactions"]:
            reactants, products = parse_equation(reaction["equation"])
            if element_totals(reactants) != element_totals(products):
                raise BuildError(f"REACTION_ATOM_IMBALANCE {reaction['reaction_id']}")
            if side_mass(reactants, masses) != side_mass(products, masses):
                raise BuildError(f"REACTION_MASS_IMBALANCE {reaction['reaction_id']}")
            intensity = reaction.get("carbon_intensity_kg_co2_per_kg_ch4")
            if intensity is not None and not close(dec(intensity), masses["CO2"] / masses["CH4"]):
                raise BuildError(f"REACTION_CARBON_INTENSITY_MISMATCH {reaction['reaction_id']}")
        n_h2 = Decimal(1) / masses["H2"]
        expected = Amounts(
            {
                "steam-reforming::natural-gas-feed-in": n_h2 / 4 * masses["CH4"],
                "steam-reforming::process-water-in": n_h2 / 4 * masses["H2O"],
                "steam-reforming::process-gas-out": n_h2 / 4 * (masses["CH4"] + masses["H2O"]),
                "shift-conversion-and-separation::process-water-in": n_h2 / 4 * masses["H2O"],
                "shift-conversion-and-separation::co2-process-out": n_h2 / 4 * masses["CO2"],
                "shift-conversion-and-separation::hydrogen-out": Decimal(1),
            },
            missing_code="PARAMETER_EXCHANGE_UNKNOWN",
        )
        authored = self.graph_amounts()
        for entry in self.parameters["stoichiometry"]["derived_coefficients"]["values"]:
            exchange_id = entry["exchange_id"]
            target = expected[exchange_id]
            if not close(dec(entry["exact"]), target):
                raise BuildError(f"PARAMETER_DERIVATION_MISMATCH {exchange_id}")
            if not close(dec(entry["in_graph"]), target):
                raise BuildError(f"PARAMETER_ROUNDING_MISMATCH {exchange_id}")
            if not close(authored[exchange_id], target):
                raise BuildError(f"GRAPH_AMOUNT_VS_STOICHIOMETRY {exchange_id} graph={authored[exchange_id]}")
        if set(expected) != {row["exchange_id"] for row in self.parameters["stoichiometry"]["derived_coefficients"]["values"]}:
            raise BuildError("STOICHIOMETRY_TABLE_COVERAGE_MISMATCH")
        left = (
            authored["steam-reforming::natural-gas-feed-in"]
            + 2 * authored["steam-reforming::process-water-in"]
        )
        right = authored["shift-conversion-and-separation::hydrogen-out"] + authored[
            "shift-conversion-and-separation::co2-process-out"
        ]
        if not close(left, right):
            raise BuildError(f"OVERALL_MASS_BALANCE_OPEN in={left} out={right}")

    def normalized(self, property_code: str) -> Decimal:
        for row in self.parameters["factor"]["normalized_quantities"]:
            if row["property_code"] == property_code:
                return dec(row["value"])
        raise BuildError(f"PARAMETER_MISSING {property_code}")

    def graph_amounts(self) -> Amounts:
        return Amounts(
            {port["_exchange_id"]: dec(port["amount"]) for port in self.graph_ports()}
        )

    def check_combustion(self) -> None:
        emission_factor = self.normalized("emission_factor")
        net_calorific_value = self.normalized("net_calorific_value")
        implied = self.normalized("implied_emission_per_mass_of_fuel")
        published = self.parameters["factor"]["as_published"]
        published_factor = dec(published["emission_factor"]["value"].replace(",", "."))
        published_ncv = dec(published["net_calorific_value"]["value"].replace(",", "."))
        if published_factor / Decimal(1000) != emission_factor:
            raise BuildError("FACTOR_NORMALISATION_MISMATCH emission_factor")
        if published_ncv != net_calorific_value:
            raise BuildError("FACTOR_NORMALISATION_MISMATCH net_calorific_value")
        oxidation = dec(self.parameters["oxidation"]["value"])
        if emission_factor * net_calorific_value * oxidation != implied:
            raise BuildError("FACTOR_CHAIN_MISMATCH implied_emission_per_mass_of_fuel")
        authored = self.graph_amounts()
        duties = {slot["slot_id"]: dec(slot["value"]) for slot in self.parameters["activities"]["slots"]}
        if duties["reformer_furnace_heat_input"] * emission_factor * oxidation != authored[
            "steam-reforming::co2-fuel-combustion-out"
        ]:
            raise BuildError("COMBUSTION_TERM_MISMATCH steam-reforming")
        if duties["process_steam_duty"] * emission_factor * oxidation != authored[
            "utility-boiler::co2-fuel-combustion-out"
        ]:
            raise BuildError("COMBUSTION_TERM_MISMATCH utility-boiler")
        for slot in self.parameters["activities"]["slots"]:
            for exchange_id in slot["exchange_ids"]:
                if exchange_id.endswith("natural-gas-fuel-in"):
                    fuel = dec(slot["value"]) / net_calorific_value
                    if not close(authored[exchange_id], fuel):
                        raise BuildError(f"ACTIVITY_FUEL_QUANTITY_MISMATCH {exchange_id}")
                    if not close(dec(slot["derived_fuel_quantity"]["value"]), fuel):
                        raise BuildError(f"PARAMETER_FUEL_QUANTITY_MISMATCH {slot['slot_id']}")
        result = self.expected["cbam"]["functional_unit_result"]
        ideal = Amounts(
            {row["exchange_id"]: dec(row["expected"]) for row in result["components"]},
            missing_code="EXPECTED_VALUE_MISSING",
        )
        rounded = Amounts(
            {row["exchange_id"]: dec(row["authored"]) for row in result["components"]},
            missing_code="EXPECTED_VALUE_MISSING",
        )
        for exchange_id, value in ideal.items():
            if not close(value, rounded[exchange_id]):
                raise BuildError(f"EXPECTED_ROUNDING_OUTSIDE_TOLERANCE {exchange_id}")
            if authored[exchange_id] != rounded[exchange_id]:
                raise BuildError(
                    f"GRAPH_AMOUNT_VS_EXPECTATION {exchange_id} graph={authored[exchange_id]} expected={rounded[exchange_id]}"
                )
        ideal_total = sum(ideal.values(), Decimal(0))
        authored_total = sum(rounded.values(), Decimal(0))
        if ideal_total != dec(result["expected"]):
            raise BuildError(f"CBAM_TOTAL_MISMATCH derived={ideal_total} != {result['expected']}")
        if authored_total != dec(result["authored_sum"]):
            raise BuildError(f"CBAM_AUTHORED_TOTAL_MISMATCH {authored_total} != {result['authored_sum']}")
        detector = self.expected["cbam"]["defect_D_H1_detector"]
        boiler = "utility-boiler::co2-fuel-combustion-out"
        if ideal_total - ideal[boiler] != dec(detector["expected_if_boiler_role_missing"]):
            raise BuildError(f"D_H1_DETECTOR_MISMATCH {ideal_total - ideal[boiler]}")
        if authored_total - rounded[boiler] != dec(detector["authored_if_boiler_role_missing"]):
            raise BuildError(f"D_H1_DETECTOR_AUTHORED_MISMATCH {authored_total - rounded[boiler]}")
        pcf = self.expected["pcf"]["foreground_boundary_co2"]
        if pcf["expected"] != result["expected"] or pcf["authored_sum"] != result["authored_sum"]:
            raise BuildError("PCF_FOREGROUND_EXPECTATION_DIVERGES_FROM_CBAM")

    def check_mfa_expectations(self) -> None:
        authored = self.graph_amounts()
        mass_inputs = [
            "steam-reforming::natural-gas-feed-in",
            "steam-reforming::natural-gas-fuel-in",
            "utility-boiler::natural-gas-fuel-in",
            "steam-reforming::process-water-in",
            "shift-conversion-and-separation::process-water-in",
        ]
        mass_outputs = [
            "shift-conversion-and-separation::hydrogen-out",
            "shift-conversion-and-separation::co2-process-out",
            "steam-reforming::co2-fuel-combustion-out",
            "utility-boiler::co2-fuel-combustion-out",
        ]
        in_total = sum((authored[item] for item in mass_inputs), Decimal(0))
        out_total = sum((authored[item] for item in mass_outputs), Decimal(0))
        segment = self.boundaries["mfa"]["segments"]
        if str(in_total) != segment["mass_inputs"]["total"]:
            raise BuildError(f"MFA_INPUT_TOTAL_MISMATCH {in_total}")
        if str(out_total) != segment["mass_outputs"]["total"]:
            raise BuildError(f"MFA_OUTPUT_TOTAL_MISMATCH {out_total}")
        expectation = self.boundaries["mfa"]["balance_expectation"]
        residual = out_total - in_total
        if str(residual) != expectation["authored_residual_out_minus_in"]:
            raise BuildError(f"MFA_RESIDUAL_MISMATCH {residual}")
        explanation = expectation["explained_by"]
        summed = sum((dec(term["value"]) for term in explanation), Decimal(0))
        if not close(summed, residual):
            raise BuildError(f"MFA_RESIDUAL_UNEXPLAINED {summed} != {residual}")
        accepted = self.expected["mfa"]
        if accepted["residual_out_minus_in"] != str(residual):
            raise BuildError("MFA_EXPECTED_RESIDUAL_MISMATCH")
        shift_in = (
            authored["shift-conversion-and-separation::process-gas-in"]
            + authored["shift-conversion-and-separation::process-water-in"]
        )
        shift_out = (
            authored["shift-conversion-and-separation::hydrogen-out"]
            + authored["shift-conversion-and-separation::co2-process-out"]
        )
        if not close(shift_in, shift_out):
            raise BuildError(f"SHIFT_NODE_IMBALANCE in={shift_in} out={shift_out}")

    def normalized_unit(self, property_code: str) -> str:
        for row in self.parameters["factor"]["normalized_quantities"]:
            if row["property_code"] == property_code:
                return str(row["unit"])
        raise BuildError(f"PARAMETER_MISSING {property_code}")

    def species_compositions(self) -> dict[str, dict[str, Decimal]]:
        """Read each species' atom composition from the seed's own declared formula strings, so a
        second seed can name species this module has never heard of."""
        weights = self.atomic_weights()
        return {
            str(row["species"]): parse_formula(str(row["formula"]), weights)
            for row in self.parameters["stoichiometry"]["molar_masses"]
        }

    def role_ports(self, **filters: object) -> set[str]:
        """Exchange ids of the ports whose declared role fields match every filter given."""
        found = set()
        for role in self.roles["roles"]:
            for port in role["ports"]:
                if all(port.get(field) == value for field, value in filters.items()):
                    found.add(f'{role["role_id"]}::{port["port_id"]}')
        return found

    def cbam_segments(self) -> list[dict]:
        return [
            segment
            for segment in (self.boundaries["cbam"].get("segments") or {}).values()
            if isinstance(segment, dict)
        ]

    def cbam_included_ids(self) -> dict[str, set[str]]:
        """The three ways a port can enter the CBAM numerator: as CO2 of this boundary, as
        precursor mass, or as an indirect electricity term. counted_for_cbam means the union."""
        buckets: dict[str, set[str]] = {"counted": set(), "precursor": set(), "indirect": set()}
        for segment in self.cbam_segments():
            conclusion = str(segment.get("conclusion"))
            kind = {PRECURSOR_CONCLUSION: "precursor", INDIRECT_CONCLUSION: "indirect"}.get(
                conclusion, "counted"
            )
            for entry in segment.get("included_exchanges") or []:
                if not isinstance(entry, dict) or "exchange_id" not in entry:
                    raise BuildError(f"CBAM_INCLUDED_ENTRY_NOT_AN_OBJECT {kind} {entry}")
                buckets[kind].add(str(entry["exchange_id"]))
        return buckets

    def cbam_dispositions(self) -> dict[str, str]:
        """The frozen ledger disposition of every counted port, so the install service restates the
        segment's conclusion instead of flattening three components into one disposition."""
        buckets = self.cbam_included_ids()
        return {
            exchange_id: disposition
            for kind, disposition in (
                ("counted", COUNTED_DISPOSITION),
                ("precursor", PRECURSOR_DISPOSITION),
                ("indirect", INDIRECT_DISPOSITION),
            )
            for exchange_id in sorted(buckets[kind])
        }

    def check_stoichiometric_demand(self) -> None:
        """Derive a precursor demand from the seed's own reaction, loss and product amounts."""
        weights = self.atomic_weights()
        masses = self.molar_masses()
        compositions = self.species_compositions()
        for species, composition in compositions.items():
            total = sum((weights[element] * count for element, count in composition.items()), Decimal(0))
            if masses[species] != total:
                raise BuildError(f"MOLAR_MASS_MISMATCH {species} table={masses[species]} formula={total}")
        reactions = {
            str(row["reaction_id"]): row for row in self.parameters["stoichiometry"]["reactions"]
        }
        for reaction in reactions.values():
            reactants, products = parse_equation(reaction["equation"], compositions)
            if element_totals(reactants, compositions) != element_totals(products, compositions):
                raise BuildError(f"REACTION_ATOM_IMBALANCE {reaction['reaction_id']}")
            if side_mass(reactants, masses) != side_mass(products, masses):
                raise BuildError(f"REACTION_MASS_IMBALANCE {reaction['reaction_id']}")
            intensity = reaction.get("carbon_intensity_kg_co2_per_kg_ch4")
            if intensity is not None and not close(
                dec(intensity), masses["CO2"] / masses["CH4"]
            ):
                raise BuildError(f"REACTION_CARBON_INTENSITY_MISMATCH {reaction['reaction_id']}")
        authored = self.graph_amounts()
        losses = {str(row["loss_id"]): row for row in self.parameters["loss"]["losses"]}
        included = self.cbam_included_ids()
        for row in self.parameters["stoichiometry"]["precursor_demand"]:
            row_id = str(row["row_id"])
            reaction = reactions.get(str(row["reaction_id"]))
            if reaction is None:
                raise BuildError(f"PRECURSOR_REACTION_UNKNOWN {row_id}")
            reactants, products = parse_equation(reaction["equation"], compositions)
            if row["product_species"] not in products or row["species"] not in reactants:
                raise BuildError(
                    f"PRECURSOR_SPECIES_NOT_IN_REACTION {row_id} product={row['product_species']} "
                    f"species={row['species']} equation={reaction['equation']}"
                )
            exchange_id = str(row["precursor_exchange_id"])
            if exchange_id not in included["precursor"]:
                raise BuildError(f"PRECURSOR_DEMAND_NOT_IN_PRECURSOR_BUCKET {exchange_id}")
            minimum = (
                authored[row["product_exchange_id"]]
                / masses[row["product_species"]]
                * (reactants[row["species"]] / products[row["product_species"]])
                * masses[row["species"]]
            )
            if not close(dec(row["stoichiometric_minimum"]), minimum):
                raise BuildError(f"PRECURSOR_MINIMUM_MISMATCH {row_id} derived={minimum}")
            loss = losses.get(str(row["loss_slot_id"]))
            if loss is None:
                raise BuildError(f"PRECURSOR_LOSS_SLOT_UNKNOWN {row_id}")
            if loss["basis"] not in LOSS_BASIS:
                raise BuildError(f"PRECURSOR_LOSS_BASIS_UNKNOWN {loss['loss_id']}")
            if dec(loss["value"]) <= 0:
                raise BuildError(f"PRECURSOR_LOSS_VALUE_NOT_AUTHORED {loss['loss_id']}")
            if loss["basis"] == "share_of_fed_mass":
                expected = minimum / (Decimal(1) - dec(loss["value"]))
                quantity = authored[exchange_id] * dec(loss["value"])
            else:
                expected = minimum + dec(loss["value"])
                quantity = dec(loss["value"])
            if not expected > minimum:
                raise BuildError(f"SEED_PRECURSOR_MASS_STOICHIOMETRIC_WITH_LOSS_OUTPUT {row_id}")
            if not close(authored[loss["loss_exchange_id"]], quantity):
                raise BuildError(f"LOSS_OUTPUT_QUANTITY_MISMATCH {loss['loss_id']}")
            if not close(dec(loss["loss_quantity"]), quantity):
                raise BuildError(f"LOSS_OUTPUT_QUANTITY_MISMATCH {loss['loss_id']} parameter")
            if not close(dec(row["exact"]), expected):
                raise BuildError(f"PRECURSOR_DEMAND_MISMATCH {row_id} derived={expected}")
            if not authored[exchange_id] > minimum:
                raise BuildError(f"SEED_PRECURSOR_MASS_NOT_ABOVE_MINIMUM {row_id}")
            if not close(authored[exchange_id], expected):
                raise BuildError(f"GRAPH_AMOUNT_VS_PRECURSOR_DEMAND {exchange_id}")

    def check_fuel_combustion_coverage(self) -> None:
        """Every combustion emission port of the boundary must be produced by exactly one declared
        activity slot, which is the generalisation of the D-H1 gate to any seed."""
        emission_factor = self.normalized("emission_factor")
        net_calorific_value = self.normalized("net_calorific_value")
        implied = self.normalized("implied_emission_per_mass_of_fuel")
        factor_unit = self.normalized_unit("emission_factor")
        ncv_unit = self.normalized_unit("net_calorific_value")
        if "/" not in factor_unit or "/" not in ncv_unit:
            raise BuildError(f"FACTOR_UNIT_PAIR_MISMATCH {factor_unit} {ncv_unit}")
        energy_basis, mass_basis = ncv_unit.split("/")[0].strip(), ncv_unit.split("/")[1].strip()
        if factor_unit.split("/")[1].strip() != energy_basis:
            raise BuildError(f"FACTOR_UNIT_PAIR_MISMATCH {factor_unit} is not per {energy_basis}")
        published = self.parameters["factor"]["as_published"]
        published_factor = dec(str(published["emission_factor"]["value"]).replace(",", "."))
        published_ncv = dec(str(published["net_calorific_value"]["value"]).replace(",", "."))
        if published_factor / Decimal(1000) != emission_factor:
            raise BuildError("FACTOR_NORMALISATION_MISMATCH emission_factor")
        if published_ncv != net_calorific_value:
            raise BuildError("FACTOR_NORMALISATION_MISMATCH net_calorific_value")
        oxidation = dec(self.parameters["oxidation"]["value"])
        if emission_factor * net_calorific_value * oxidation != implied:
            raise BuildError("FACTOR_CHAIN_MISMATCH implied_emission_per_mass_of_fuel")
        authored = self.graph_amounts()
        ports = {port["_exchange_id"]: port for port in self.graph_ports()}
        combustion = self.role_ports(emission_kind="combustion")
        fuels = self.role_ports(role="fuel")
        counted = self.cbam_included_ids()["counted"]
        bound: dict[str, str] = {}
        for slot in self.parameters["activities"]["slots"]:
            slot_id = str(slot["slot_id"])
            if slot["unit"] != energy_basis:
                raise BuildError(f"ACTIVITY_UNIT_MISMATCH {slot_id} slot={slot['unit']} factor={energy_basis}")
            duty = dec(slot["value"])
            terms = [item for item in slot["exchange_ids"] if item in combustion]
            fuel_ports = [item for item in slot["exchange_ids"] if item in fuels]
            others = [item for item in slot["exchange_ids"] if item not in terms + fuel_ports]
            if others:
                raise BuildError(f"COMBUSTION_SLOT_EXCHANGE_NOT_ELEMENTARY {slot_id} {others}")
            if len(terms) != 1:
                raise BuildError(f"COMBUSTION_SLOT_UNBOUND {slot_id} terms={terms}")
            term = terms[0]
            if term in bound:
                raise BuildError(f"COMBUSTION_TERM_BOUND_TWICE {term} {bound[term]}+{slot_id}")
            if term not in counted:
                raise BuildError(f"COMBUSTION_TERM_NOT_COUNTED {term}")
            bound[term] = slot_id
            if authored[term] != duty * emission_factor * oxidation:
                raise BuildError(f"COMBUSTION_TERM_MISMATCH {term}")
            for exchange_id in fuel_ports:
                if ports[exchange_id]["unit"] != mass_basis:
                    raise BuildError(f"ACTIVITY_FUEL_PORT_UNIT {exchange_id} unit={ports[exchange_id]['unit']}")
                fuel = duty / net_calorific_value
                if not close(authored[exchange_id], fuel):
                    raise BuildError(f"ACTIVITY_FUEL_QUANTITY_MISMATCH {exchange_id}")
                derived = slot.get("derived_fuel_quantity") or {}
                if not close(dec(derived.get("value", "0")), fuel):
                    raise BuildError(f"PARAMETER_FUEL_QUANTITY_MISMATCH {slot_id}")
                if str(derived.get("unit", "")).split()[:1] != [mass_basis]:
                    raise BuildError(f"ACTIVITY_FUEL_UNIT_MISMATCH {slot_id} unit={derived.get('unit')}")
        for term in sorted(combustion - set(bound)):
            raise BuildError(f"COMBUSTION_TERM_WITHOUT_SLOT {term}")
        for exchange_id in sorted(fuels - {item for slot in self.parameters["activities"]["slots"] for item in slot["exchange_ids"]}):
            raise BuildError(f"FUEL_PORT_WITHOUT_ACTIVITY_SLOT {exchange_id}")

    def check_mass_balance(self) -> None:
        """The seed's own material flow ledger, reconciled port by port against the graph."""
        authored = self.graph_amounts()
        ports = {port["_exchange_id"]: port for port in self.graph_ports()}
        mfa = self.boundaries["mfa"]
        mass_unit = str(mfa["result_contract"]["unit"])
        segments = {
            name: segment
            for name, segment in (mfa.get("segments") or {}).items()
            if isinstance(segment, dict)
        }
        sums = {"in": Decimal(0), "out": Decimal(0)}
        seen: dict[str, str] = {}
        totals: dict[str, str] = {}
        for name, segment in sorted(segments.items()):
            role = segment.get("in_mass_sum")
            if role not in ("in", "out", "none", None):
                raise BuildError(f"MFA_SEGMENT_SUM_INVALID {name}/{role}")
            for entry in segment.get("entries") or []:
                exchange_id = str(entry.get("exchange_id") or "")
                port = ports.get(exchange_id)
                if port is None:
                    raise BuildError(f"MFA_ENTRY_UNKNOWN {exchange_id}")
                if exchange_id in seen:
                    raise BuildError(
                        f"MFA_PORT_CLASSIFIED_TWICE {exchange_id} {seen[exchange_id]}+{name}"
                    )
                seen[exchange_id] = name
                amount = dec(entry["amount"])
                if amount != dec(port["amount"]):
                    raise BuildError(f"MFA_ENTRY_AMOUNT {exchange_id} ledger={amount} graph={port['amount']}")
                if role is None:
                    continue
                if str(entry.get("unit") or port["unit"]) != port["unit"]:
                    raise BuildError(f"MFA_ENTRY_UNIT {exchange_id}")
                if role in ("in", "out"):
                    if port["unit"] != mass_unit:
                        raise BuildError(f"MFA_MASS_SUM_WITH_NON_MASS {exchange_id} unit={port['unit']}")
                    if (port["direction"] == "input") != (role == "in"):
                        raise BuildError(f"MFA_ENTRY_DIRECTION {exchange_id}")
                    sums[role] += amount
        for exchange_id in sorted(set(ports) - set(seen)):
            raise BuildError(f"MFA_PORT_UNACCOUNTED {exchange_id}")
        for name, segment in segments.items():
            if segment.get("in_mass_sum") in ("in", "out"):
                key = str(segment["in_mass_sum"])
                if str(sums[key]) != str(segment.get("total")):
                    raise BuildError(f"MFA_TOTAL_MISMATCH {name} ledger={segment.get('total')} computed={sums[key]}")
                totals[key] = str(segment.get("total"))
        if set(totals) != {"in", "out"}:
            raise BuildError(f"MFA_MASS_SUM_SEGMENTS_MISSING {sorted(totals)}")
        expectation = mfa.get("balance_expectation") or {}
        residual = sums["out"] - sums["in"]
        if str(residual) != str(expectation.get("authored_residual_out_minus_in")):
            raise BuildError(f"MFA_RESIDUAL_MISMATCH {residual}")
        terms = expectation.get("explained_by") or []
        if not terms:
            raise BuildError("MFA_RESIDUAL_UNEXPLAINED no terms are authored")
        summed = sum((dec(term["value"]) for term in terms), Decimal(0))
        if not close(summed, residual):
            raise BuildError(f"MFA_RESIDUAL_UNEXPLAINED {summed} != {residual}")
        accepted = self.expected["mfa"]
        if str(accepted["mass_in"]) != totals["in"] or str(accepted["mass_out"]) != totals["out"]:
            raise BuildError(f"MFA_ACCEPTED_TOTALS_MISMATCH {totals}")
        if str(accepted["residual_out_minus_in"]) != str(residual):
            raise BuildError("MFA_ACCEPTED_RESIDUAL_MISMATCH")
        gaps = {str(gap["id"]) for gap in self.clause_mapping["modeling_gaps"]}
        closures = {str(row["node_id"]): row for row in mfa.get("node_closures") or []}
        if set(closures) != {node["id"] for node in self.graph["nodes"]}:
            raise BuildError(
                f"MFA_NODE_CLOSURE_SET nodes={sorted(node['id'] for node in self.graph['nodes'])} "
                f"ledger={sorted(closures)}"
            )
        for node in self.graph["nodes"]:
            node_id = node["id"]
            row = closures[node_id]
            mass_ports = [
                port for port in node["inputs"] + node["outputs"] if port["unit"] == mass_unit
            ]
            computed_in = sum((dec(port["amount"]) for port in mass_ports if port["direction"] == "input"), Decimal(0))
            computed_out = sum((dec(port["amount"]) for port in mass_ports if port["direction"] == "output"), Decimal(0))
            if str(row["mass_in"]) != str(computed_in) or str(row["mass_out"]) != str(computed_out):
                raise BuildError(
                    f"MFA_NODE_CLOSURE_AMOUNT {node_id} authored={row['mass_in']}/{row['mass_out']} "
                    f"graph={computed_in}/{computed_out}"
                )
            balanced = computed_in == computed_out
            if row["expectation"] not in ("closed", "open_with_gap"):
                raise BuildError(f"MFA_NODE_CLOSURE_EXPECTATION {node_id}")
            if balanced and row["expectation"] != "closed":
                raise BuildError(f"MFA_NODE_CLOSURE_BALANCED_AS_OPEN {node_id}")
            if not balanced:
                if row["expectation"] != "open_with_gap":
                    raise BuildError(f"MFA_NODE_CLOSURE_OPEN_WITHOUT_GAP {node_id}")
                if row.get("gap_ref") not in gaps:
                    raise BuildError(f"MFA_NODE_CLOSURE_GAP_UNREGISTERED {node_id} gap_ref={row.get('gap_ref')}")

    def check_result_expectations(self) -> None:
        """The acceptance ledger must restate the boundary buckets, not a parallel number list."""
        authored = self.graph_amounts()
        included = self.cbam_included_ids()
        result = self.expected["cbam"]["functional_unit_result"]
        components = result.get("emission_components")
        if not isinstance(components, list) or not components:
            raise BuildError("RESULT_COMPONENTS_MISSING")
        kinds = [str(row.get("component") or "") for row in components]
        if len(set(kinds)) != len(kinds) or any(kind not in COMPONENT_KINDS for kind in kinds):
            raise BuildError(f"RESULT_COMPONENT_KIND_INVALID {kinds}")
        al_kg = dec(self.boundaries["cbam"]["functional_unit"]["kg_per_tonne"])
        buckets = {"direct_co2": "counted", "precursor_mass": "precursor", "indirect_electricity": "indirect"}
        expected_total = Decimal(0)
        authored_total = Decimal(0)
        direct_authored = None
        for row in components:
            kind = str(row["component"])
            exchange_ids = [str(item) for item in row.get("exchange_ids") or []]
            if not exchange_ids:
                raise BuildError(f"RESULT_COMPONENT_EXCHANGES_MISSING {kind}")
            if set(exchange_ids) != included[buckets[kind]]:
                raise BuildError(
                    f"RESULT_COMPONENT_BUCKET_MISMATCH {kind} ledger={sorted(included[buckets[kind]])} "
                    f"component={sorted(exchange_ids)}"
                )
            if kind == "direct_co2":
                direct_authored = sum((authored[item] for item in exchange_ids), Decimal(0)) / al_kg
                if dec(row["authored"]) != direct_authored:
                    raise BuildError(f"RESULT_DIRECT_MISMATCH authored={row['authored']} computed={direct_authored}")
                if not close(dec(row["expected"]), dec(row["authored"])):
                    raise BuildError(f"RESULT_DIRECT_DERIVATION_MISMATCH {kind}")
            if kind == "precursor_mass":
                source = row.get("source") or {}
                self._check_precursor_source(row_id=kind, source=source)
                al_g = dec(row["al_g"])
                if authored[str(row["al_exchange_id"])] != al_g:
                    raise BuildError(f"RESULT_PRECURSOR_ACTIVITY_LEVEL {row['al_exchange_id']}")
                if dec(row["mass_authored"]) != authored[exchange_ids[0]]:
                    raise BuildError(f"RESULT_PRECURSOR_MASS_MISMATCH {exchange_ids[0]}")
                if not close(dec(row["mass_expected"]), dec(row["mass_exact"])):
                    raise BuildError("RESULT_PRECURSOR_MASS_DERIVATION_MISMATCH")
                see = dec(row["see"]["value"])
                see_unit = str(row["see"]["unit"])
                if "/" not in see_unit or see_unit.split("/")[0].strip() != str(row["unit"]).split("/")[0].strip():
                    raise BuildError(f"RESULT_PRECURSOR_SEE_UNIT {see_unit} component={row['unit']}")
                term_authored = dec(row["mass_authored"]) / al_g * see
                if dec(row["authored"]) != term_authored:
                    raise BuildError(f"RESULT_PRECURSOR_TERM_MISMATCH authored={row['authored']} computed={term_authored}")
                if not close(dec(row["expected"]), dec(row["mass_exact"]) / al_g * see):
                    raise BuildError("RESULT_PRECURSOR_TERM_DERIVATION_MISMATCH")
            if kind == "indirect_electricity":
                if row.get("state") != "formula_only":
                    raise BuildError(f"RESULT_INDIRECT_STATE {row.get('state')}")
                if row.get("emission_factor") is not None:
                    raise BuildError("CBAM_INDIRECT_FACTOR_AUTHORED_IN_SEED")
                if row.get("expected") is not None or row.get("authored") is not None:
                    raise BuildError("CBAM_INDIRECT_NUMBER_AUTHORED_IN_SEED")
                quantity = sum((authored[item] for item in exchange_ids), Decimal(0))
                if dec(row["activity_total"]) != quantity:
                    raise BuildError(f"RESULT_INDIRECT_ACTIVITY_MISMATCH {quantity}")
            if row.get("authored") is not None:
                authored_total += dec(row["authored"])
            if row.get("expected") is not None:
                expected_total += dec(row["expected"])
        if any(row.get("expected") is None for row in components) and not result.get("partial_result"):
            raise BuildError("RESULT_PARTIAL_UNDECLARED")
        if not close(expected_total, dec(result["expected"])):
            raise BuildError(f"CBAM_TOTAL_MISMATCH derived={expected_total} != {result['expected']}")
        if authored_total != dec(result["authored_sum"]):
            raise BuildError(
                f"CBAM_AUTHORED_TOTAL_MISMATCH {authored_total} != {result['authored_sum']}"
            )
        pcf = self.expected["pcf"]["foreground_boundary_co2"]
        if dec(pcf["authored_sum"]) != direct_authored or not close(dec(pcf["expected"]), direct_authored):
            raise BuildError(f"PCF_FOREGROUND_NOT_THE_DIRECT_TERM {pcf['authored_sum']}")

    def _check_precursor_source(self, *, row_id: str, source: dict) -> None:
        """A precursor specific value is only traceable if the seed pins the exact package, and
        the package's own seed, that produced it."""
        for field in (
            "seed_id",
            "seed_version",
            "seed_directory",
            "package_ref",
            "package_content_sha256",
            "bundle_content_sha256",
        ):
            if not source.get(field):
                raise BuildError(f"PRECURSOR_SOURCE_FIELD_MISSING {row_id}/{field}")
        if "latest" in str(source["package_ref"]).lower():
            raise BuildError(f"PRECURSOR_SOURCE_REF_NOT_PINNED {source['package_ref']}")
        manifest_path = (
            REPO_ROOT / "cases" / "standard-lca-seeds" / str(source["seed_directory"]) / "seed.json"
        )
        if not manifest_path.is_file():
            raise BuildError(f"PRECURSOR_SOURCE_SEED_DIRECTORY {source['seed_directory']}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("seed_id") != source["seed_id"] or manifest.get("version") != source["seed_version"]:
            raise BuildError(f"PRECURSOR_SOURCE_SEED_IDENTITY {row_id}")
        if str((manifest.get("content_pins") or {}).get("bundle_content_sha256")) != source["bundle_content_sha256"]:
            raise BuildError(f"PRECURSOR_SOURCE_BUNDLE_PIN_DRIFT {row_id}")
        named = [
            entry
            for entry in manifest.get("method_package_refs") or []
            if f"{entry.get('package_id')}@{entry.get('version')}" == source["package_ref"]
        ]
        if len(named) != 1:
            raise BuildError(f"PRECURSOR_SOURCE_PACKAGE_UNKNOWN {source['package_ref']}")
        if str(named[0].get("content_sha256")) != source["package_content_sha256"]:
            raise BuildError(f"PRECURSOR_SOURCE_PIN_DRIFT {source['package_ref']}")

    def check_nitrogen_basis(self) -> None:
        """The legal denominator is a stated parameter with a source, never a frontend constant."""
        nitrogen = self.parameters["nitrogen"]
        if nitrogen["claim_level"] not in NITROGEN_CLAIM_LEVELS:
            raise BuildError(f"NITROGEN_CLAIM_LEVEL_UNKNOWN {nitrogen['claim_level']}")
        product_form = nitrogen.get("product_form")
        if product_form not in PRODUCT_FORMS:
            raise BuildError(f"NITROGEN_PRODUCT_FORM_UNKNOWN {product_form}")
        if product_form == "hydrous_solution" and not nitrogen.get("concentration"):
            raise BuildError("NITROGEN_CONCENTRATION_MISSING")
        if nitrogen.get("composition_adjustment", {}).get("applied") and not nitrogen.get("composition_range"):
            raise BuildError("CBAM_TRIAL_COMPOSITION_ADJUSTMENT_WITHOUT_RANGE")
        weights = self.atomic_weights()
        masses = self.molar_masses()
        compositions = self.species_compositions()
        derivation = nitrogen["derivation"]
        species, element = str(derivation["product_species"]), str(derivation["element"])
        if species not in masses:
            raise BuildError(f"NITROGEN_PRODUCT_SPECIES_UNKNOWN {species}")
        if element not in compositions[species]:
            raise BuildError(f"NITROGEN_ELEMENT_NOT_IN_PRODUCT {species} {element}")
        recomputed = dec(derivation["atoms_per_molecule"]) * weights[element] / masses[species]
        if not close(recomputed, dec(nitrogen["value"])):
            raise BuildError(f"NITROGEN_CONTENT_DERIVATION_MISMATCH derived={recomputed}")
        self._check_nitrogen_published_source(nitrogen)
        authored = self.graph_amounts()
        content = dec(nitrogen["value"])
        if not close(
            authored[str(nitrogen["model_agreement"]["reactant_exchange_id"])],
            content * authored[str(nitrogen["model_agreement"]["product_exchange_id"])],
        ):
            raise BuildError("NITROGEN_MODEL_AGREEMENT_MISMATCH")
        basis = self.expected["nitrogen_basis"]
        cn_code = str(self.boundaries["cbam"]["goods_identity"]["cn_code"])
        applicable = cn_code in [str(item) for item in nitrogen["applicable_cn_codes"]]
        if bool(basis.get("applies")) is not applicable:
            raise BuildError(f"NITROGEN_BASIS_APPLIES_MISMATCH cn_code={cn_code} applies={basis.get('applies')}")
        if not applicable:
            return
        result = self.expected["cbam"]["functional_unit_result"]
        if str(basis["per_tonne_product"]["value"]) != str(result["authored_sum"]):
            raise BuildError("NITROGEN_DUAL_BASIS_PRODUCT_MISMATCH")
        if str(basis["content_of_n"]["value"]) != str(nitrogen["value"]):
            raise BuildError("NITROGEN_DUAL_BASIS_CONTENT_MISMATCH")
        if basis["content_of_n"]["parameter_ref"] != self.profile["parameter_files"]["nitrogen"]:
            raise BuildError(f"NITROGEN_PARAMETER_REF_DRIFT {basis['content_of_n']['parameter_ref']}")
        if basis["content_of_n"]["claim_level"] != nitrogen["claim_level"]:
            raise BuildError("NITROGEN_CLAIM_LEVEL_ECHO_MISMATCH")
        if not close(
            dec(basis["per_kg_n"]["value"]),
            dec(basis["per_tonne_product"]["value"]) / content,
        ):
            raise BuildError("NITROGEN_DUAL_BASIS_CONVERSION_MISMATCH")
        for row in result["emission_components"]:
            if row.get("component") != "precursor_mass":
                continue
            m_i = dec(row["mass_authored"]) / dec(row["al_g"])
            if dec(row["m_i_per_tonne_product"]) != m_i:
                raise BuildError(f"NITROGEN_DUAL_BASIS_M_I_PRODUCT {row['m_i_per_tonne_product']} != {m_i}")
            if not close(dec(row["m_i_per_kg_n"]), m_i / content):
                raise BuildError(f"NITROGEN_DUAL_BASIS_M_I_PER_KG_N {row['m_i_per_kg_n']}")

    def _check_nitrogen_published_source(self, nitrogen: dict) -> None:
        source = nitrogen["published_source"]
        for field in ("kind", "file", "content_sha256", "transcribed_fields"):
            if not source.get(field):
                raise BuildError(f"NITROGEN_PUBLISHED_SOURCE_FIELD_MISSING {field}")
        path = REPO_ROOT / str(source["file"])
        if not path.is_file():
            raise BuildError(f"NITROGEN_PUBLISHED_FILE_MISSING {source['file']}")
        if digest(path.read_bytes()) != source["content_sha256"]:
            raise BuildError(f"NITROGEN_PUBLISHED_HASH_MISMATCH {source['file']}")
        named = json.loads(path.read_text(encoding="utf-8"))
        rows = {str(row["element"]): dec(row["value"]) for row in named.get("atomic_weights") or []}
        weights = self.atomic_weights()
        for entry in source["transcribed_fields"]:
            element = str(entry["element"])
            if element not in rows:
                raise BuildError(f"NITROGEN_TRANSCRIBED_FIELD_MISSING {element}")
            if rows[element] != dec(entry["value"]) or weights.get(element) != rows[element]:
                raise BuildError(f"NITROGEN_TRANSCRIBED_VALUE_MISMATCH {element}")
        for element in source.get("not_in_named_file") or []:
            if str(element) in rows:
                raise BuildError(f"NITROGEN_TRANSCRIBED_PROVENANCE_CLAIM {element}")

    # ---------- structure layer ----------

    def check_roles(self) -> None:
        required = set(self.roles["mandatory_role_check"]["required_sub_roles"])
        present = {sub["sub_role_id"] for role in self.roles["roles"] for sub in role["merged_sub_roles"]}
        if required != present:
            raise BuildError(
                f"MANDATORY_ROLE_MISMATCH missing={sorted(required - present)} extra={sorted(present - required)}"
            )
        nodes = {node["id"]: node for node in self.graph["nodes"]}
        if set(nodes) != {role["role_id"] for role in self.roles["roles"]}:
            raise BuildError("ROLE_NODE_SET_MISMATCH")
        for role in self.roles["roles"]:
            node = nodes[role["role_id"]]
            graph_ports = {port["id"] for port in node["inputs"] + node["outputs"]}
            declared = {port["port_id"] for port in role["ports"]}
            if graph_ports != declared:
                raise BuildError(
                    f"PORT_SET_MISMATCH {role['role_id']} only_graph={sorted(graph_ports - declared)} "
                    f"only_roles={sorted(declared - graph_ports)}"
                )
            for port in role["ports"]:
                if port["flow_role"] == "carbon_dioxide_fossil" and port["direction"] != "output":
                    raise BuildError(f"EMISSION_PORT_DIRECTION {role['role_id']}/{port['port_id']}")
                self.check_port_wiring(node, port)

    def check_port_wiring(self, node: dict, declared: dict) -> None:
        graph_port = next(
            (port for port in node["inputs"] + node["outputs"] if port["id"] == declared["port_id"]), None
        )
        if graph_port is None:
            raise BuildError(f"PORT_UNAUTHORED {node['id']}/{declared['port_id']}")
        flow_uuids = {row["role"]: row["flow_uuid"] for row in self.flow_dependencies["dependencies"]}
        expected_uuid = flow_uuids.get(declared["flow_role"])
        if expected_uuid is None:
            raise BuildError(f"FLOW_ROLE_UNDECLARED {declared['flow_role']}")
        if graph_port["flowUuid"] != expected_uuid:
            raise BuildError(f"PORT_FLOW_ROLE_MISMATCH {node['id']}/{declared['port_id']}")
        if graph_port["direction"] != declared["direction"]:
            raise BuildError(f"PORT_DIRECTION_CONFLICT {node['id']}/{declared['port_id']}")
        element_flow = declared["flow_role"] == "carbon_dioxide_fossil"
        if (graph_port["type"] == "biosphere") is not element_flow:
            raise BuildError(f"PORT_FLOW_SEMANTIC_CONFLICT {node['id']}/{declared['port_id']}")

    def check_boundaries(self) -> None:
        blob = json.dumps(self.boundaries, ensure_ascii=False)
        corpus = json.dumps(
            [self.roles, self.boundaries, list(self.parameters.values()), self.graph],
            ensure_ascii=False,
        )
        must_appear = [
            f'{role["role_id"]}::{port["port_id"]}'
            for role in self.roles["roles"]
            for port in role["ports"]
            if port.get("role") in {"emission_source", "reference_product", "fuel", "feedstock", "auxiliary_energy"}
        ]
        for exchange_id in must_appear:
            if exchange_id not in blob:
                raise BuildError(f"BOUNDARY_ITEM_UNACCOUNTED {exchange_id}")
        counted = set().union(*self.cbam_included_ids().values())
        flags = {
            f'{role["role_id"]}::{port["port_id"]}': port.get("counted_for_cbam")
            for role in self.roles["roles"]
            for port in role["ports"]
        }
        for exchange_id in sorted(counted):
            flag = flags.get(exchange_id)
            if flag is False:
                raise BuildError(f"CBAM_DOUBLE_FLAG {exchange_id}")
            if flag is not True:
                raise BuildError(f"CBAM_COUNT_FLAG_CONFLICT {exchange_id}")
        for exchange_id, flag in flags.items():
            if flag is True and exchange_id not in counted:
                raise BuildError(f"CBAM_COUNTED_PORT_MISSING_FROM_BOUNDARY {exchange_id}")
        for clause in self.clause_mapping["clauses"]:
            clause_id = clause["id"]
            if not re.search(rf"{re.escape(clause_id)}(?!\d)", corpus):
                raise BuildError(f"CLAUSE_NOT_CONSUMED_BY_SEED {clause_id}")
            quoted = next(
                (clause.get(field) for field in ("quote", "quote_original", "quote_consolidated") if clause.get(field)),
                None,
            )
            if not quoted:
                raise BuildError(f"CLAUSE_EVIDENCE_MISSING {clause_id}/quote")
            for field in ("locator", "anchor", "model_role", "validation"):
                if not clause.get(field):
                    raise BuildError(f"CLAUSE_EVIDENCE_MISSING {clause_id}/{field}")
            if clause.get("amended_in"):
                if not clause.get("required_evidence") or "side by side" not in clause["required_evidence"]:
                    raise BuildError(f"CLAUSE_AMENDED_EVIDENCE_RULE {clause_id}")
                if not (clause.get("quote_original") and clause.get("quote_consolidated")):
                    raise BuildError(f"CLAUSE_AMENDED_WORDING_MISSING {clause_id}")
        for gap in self.clause_mapping["modeling_gaps"]:
            if gap["id"] not in corpus:
                raise BuildError(f"MODELING_GAP_NOT_REFERENCED {gap['id']}")
        for name, boundary in self.boundaries.items():
            application = boundary["application"]
            for segment in boundary.get("segments", {}).values():
                conclusion = segment.get("conclusion")
                if conclusion not in BOUNDARY_CONCLUSIONS:
                    raise BuildError(f"BOUNDARY_CONCLUSION_INVALID {application}/{conclusion}")
                segment_has_clause = bool(self.clause_pattern.search(str(segment.get("clause", ""))))

                def cited(entry) -> bool:
                    if not isinstance(entry, dict):
                        return segment_has_clause
                    return bool(self.clause_pattern.search(str(entry.get("clause", ""))))

                for entry in segment.get("excluded_exchanges", []):
                    if isinstance(entry, dict) and not (entry.get("basis") or entry.get("reason")):
                        raise BuildError(f"EXCLUSION_WITHOUT_REASON {application}")
                    if not cited(entry):
                        raise BuildError(f"EXCLUSION_WITHOUT_CLAUSE {application}")
                if name == "cbam":
                    for entry in segment.get("included_exchanges", []):
                        if not cited(entry):
                            raise BuildError(f"INCLUSION_WITHOUT_CLAUSE {entry}")

    def check_cbam_candidate_universe(self) -> None:
        cbam = self.boundaries["cbam"]
        segments = [
            segment
            for segment in cbam.get("segments", {}).values()
            if isinstance(segment, dict)
        ]
        buckets: dict[str, list] = {
            "counted": [
                entry
                for segment in segments
                if segment.get("conclusion") not in NON_DIRECT_CONCLUSIONS
                for entry in segment.get("included_exchanges", [])
            ],
            # a precursor is neither counted as CO2 here nor excluded: it is counted as mass
            "precursor": [
                entry
                for segment in segments
                if segment.get("conclusion") == PRECURSOR_CONCLUSION
                for entry in segment.get("included_exchanges", [])
            ],
            # consumed electricity of a good that Annex II does not carve out is counted, but as
            # an indirect component, so it may not share the direct CO2 bucket
            "indirect": [
                entry
                for segment in segments
                if segment.get("conclusion") == INDIRECT_CONCLUSION
                for entry in segment.get("included_exchanges", [])
            ],
            "excluded": [
                entry for segment in segments for entry in segment.get("excluded_exchanges", [])
            ],
            "not_applicable": list(cbam.get("not_applicable", [])),
        }
        seen: dict[str, str] = {}
        for disposition, entries in buckets.items():
            for entry in entries:
                if not isinstance(entry, dict) or "exchange_id" not in entry:
                    raise BuildError(f"CBAM_CANDIDATE_ENTRY_NOT_AN_OBJECT {disposition} {entry}")
                exchange_id = entry["exchange_id"]
                if exchange_id in seen:
                    raise BuildError(
                        f"CBAM_CANDIDATE_PORT_CLASSIFIED_TWICE {exchange_id} "
                        f"{seen[exchange_id]}+{disposition}"
                    )
                seen[exchange_id] = disposition
        for disposition in ("excluded", "not_applicable", "precursor", "indirect"):
            for entry in buckets[disposition]:
                if not (entry.get("basis") or entry.get("reason")):
                    raise BuildError(f"CBAM_CANDIDATE_BASIS_MISSING {entry['exchange_id']}")
                if not self.clause_pattern.search(str(entry.get("clause", ""))):
                    raise BuildError(f"CBAM_CANDIDATE_CLAUSE_MISSING {entry['exchange_id']}")
        # a direct emission is an elementary exchange: a technosphere port in this bucket would
        # be an electricity or material input reported as CO2 of this boundary. The indirect
        # bucket is its mirror image, so a CO2 exchange there is a mis-disposition too.
        port_type = {
            f'{node["id"]}::{port["id"]}': port["type"]
            for node in self.graph["nodes"]
            for port in node["inputs"] + node["outputs"]
        }
        for disposition, expected_type, refusal in (
            ("counted", "biosphere", "CBAM_COUNTED_PORT_NOT_ELEMENTARY"),
            ("indirect", "technosphere", "CBAM_INDIRECT_PORT_NOT_TECHNOSPHERE"),
        ):
            for entry in buckets[disposition]:
                exchange_id = entry["exchange_id"]
                if port_type.get(exchange_id) != expected_type:
                    raise BuildError(f"{refusal} {exchange_id}")
        for role in self.roles["roles"]:
            for port in role["ports"]:
                exchange_id = f'{role["role_id"]}::{port["port_id"]}'
                if exchange_id not in seen:
                    raise BuildError(f"CBAM_CANDIDATE_PORT_UNCLASSIFIED {exchange_id}")
        ports = {
            f'{role["role_id"]}::{port["port_id"]}'
            for role in self.roles["roles"]
            for port in role["ports"]
        }
        for exchange_id in seen:
            if exchange_id not in ports:
                raise BuildError(f"CBAM_CANDIDATE_PORT_UNKNOWN {exchange_id}")
        flow_roles = {row["role"] for row in self.flow_dependencies["dependencies"]}
        for segment in segments:
            attribution = segment.get("attribution")
            if attribution is not None and attribution not in PRECURSOR_ATTRIBUTIONS:
                raise BuildError(f"CBAM_PRECURSOR_ATTRIBUTION_UNKNOWN {attribution}")
            for entry in segment.get("checked_inputs", []):
                if not isinstance(entry, dict):
                    raise BuildError(f"CBAM_CANDIDATE_ENTRY_NOT_AN_OBJECT precursors {entry}")
                self._check_membership_row(entry, flow_roles)

    def _check_membership_row(self, entry: dict, flow_roles: set) -> None:
        """A row that claims Annex I membership must say which of the three states it is in."""
        declared = entry.get("membership")
        if declared is None:
            return
        subject = str(entry.get("flow_role") or entry.get("exchange_id") or "")
        if not subject:
            raise BuildError(f"CBAM_CANDIDATE_MEMBERSHIP_SUBJECT_MISSING {entry}")
        if declared not in PRECURSOR_MEMBERSHIPS:
            raise BuildError(f"CBAM_CANDIDATE_MEMBERSHIP_UNKNOWN {subject} {declared}")
        if entry.get("flow_role") is not None and entry["flow_role"] not in flow_roles:
            raise BuildError(f"CBAM_CANDIDATE_MEMBERSHIP_FLOW_UNKNOWN {subject}")
        listed = entry.get("annex_i_listed")
        if not isinstance(listed, bool) or listed != (declared != "not_listed"):
            raise BuildError(
                f"CBAM_CANDIDATE_MEMBERSHIP_FLAG_CONFLICT {subject} "
                f"membership={declared} annex_i_listed={listed}"
            )
        if not self.clause_pattern.search(str(entry.get("clause", ""))):
            raise BuildError(f"CBAM_CANDIDATE_MEMBERSHIP_CLAUSE_MISSING {subject}")

    def check_flow_dependencies(self) -> None:
        dependencies = self.flow_dependencies["dependencies"]
        owned = {row["flow_uuid"] for row in self.owned_flows["rows"]}
        declared = set()
        for row in dependencies:
            disposition = row["disposition"]
            flow_uuid = row["flow_uuid"]
            declared.add(flow_uuid)
            if disposition not in {"bundled_owned", "verify_present", "blocked"}:
                raise BuildError(f"FLOW_DISPOSITION_UNKNOWN {row['role']}")
            if disposition == "bundled_owned":
                if flow_uuid not in owned:
                    raise BuildError(f"FLOW_BUNDLE_MISSING {flow_uuid}")
                if not row.get("why_not_upstream"):
                    raise BuildError(f"OWNED_FLOW_WITHOUT_REASON {row['role']}")
            if disposition == "verify_present":
                if flow_uuid in owned:
                    raise BuildError(f"VERIFY_PRESENT_FLOW_IS_ALSO_BUNDLED {flow_uuid}")
                observed = row.get("observed") or {}
                for field in ("flow_name_en", "unit_group", "default_unit"):
                    if field not in observed:
                        raise BuildError(f"OBSERVED_ROW_INCOMPLETE {row['role']}/{field}")
                if not self.flow_dependencies["probe"].get("caveat"):
                    raise BuildError("PROBE_CAVEAT_MISSING")
                if row.get("provided_by") is not None:
                    self._check_provided_by(row, row["provided_by"])
            if disposition == "blocked":
                raise BuildError(f"FLOW_DEPENDENCY_BLOCKED {row['role']}")
        used = {
            str(obj.get("flowUuid") or obj.get("flow_uuid"))
            for obj in walk(self.graph)
            if (obj.get("flowUuid") or obj.get("flow_uuid"))
        }
        if missing := sorted(used - declared):
            raise BuildError(f"FLOW_DEPENDENCY_UNDECLARED {missing}")
        groups = self.flow_dependencies["unit_groups"]
        declared_groups = {row["observed"]["source_uuid"] for row in groups}
        used_groups = {
            str(obj["unitGroupUuid"]) for obj in walk(self.graph) if obj.get("unitGroupUuid")
        }
        if open_items := sorted(used_groups - declared_groups):
            raise BuildError(f"UNIT_GROUP_UNDECLARED {open_items}")
        for row in groups:
            if row["disposition"] != "verify_present":
                raise BuildError(f"UNIT_GROUP_DISPOSITION {row['name']}")

    def _check_provided_by(self, row: dict, provided: dict) -> None:
        """Reusing another seed's catalog flow is a versioned prerequisite, so the builder
        re-derives the identity and reads the pinned hash from the named seed's own manifest."""
        for field in ("seed_id", "seed_version", "flow_key", "seed_directory", "bundle_content_sha256"):
            if not provided.get(field):
                raise BuildError(f"CROSS_SEED_PREREQUISITE_FIELD_MISSING {row['role']}/{field}")
        namespace = uuid.UUID(self.identity["namespace"])
        derived = str(
            uuid.uuid5(
                namespace,
                f"flow|{provided['seed_id']}|{provided['seed_version']}|{provided['flow_key']}",
            )
        )
        if row["flow_uuid"] != derived:
            raise BuildError(
                f"CROSS_SEED_FLOW_IDENTITY_MISMATCH {row['role']} "
                f"declared={row['flow_uuid']} derived={derived}"
            )
        manifest_path = (
            REPO_ROOT / "cases" / "standard-lca-seeds" / provided["seed_directory"] / "seed.json"
        )
        if not manifest_path.is_file():
            # The public steel package carries only the two exact catalog rows, not the
            # hydrogen model. Its provenance descriptor retains the original bundle pin.
            if self.seed_id != "nebula.iron-steel.bf-bof-crude-steel":
                raise BuildError(f"CROSS_SEED_PREREQUISITE_DIRECTORY {provided['seed_directory']}")
            from .steel_catalog_prerequisite import load_steel_catalog_prerequisite
            try:
                descriptor, _, rows = load_steel_catalog_prerequisite()
            except (OSError, ValueError, KeyError) as error:
                raise BuildError(f"CROSS_SEED_PREREQUISITE_RESOURCE {row['role']}: {error}") from error
            expected_source = (provided["seed_id"], provided["seed_version"], provided["bundle_content_sha256"])
            observed_source = (descriptor["source_seed_id"], descriptor["source_seed_version"],
                               descriptor["source_bundle_content_sha256"])
            if observed_source != expected_source:
                raise BuildError(f"CROSS_SEED_PREREQUISITE_PIN_DRIFT {row['role']}")
            matching = [item for item in rows if item["flow_uuid"] == row["flow_uuid"]]
            if len(matching) != 1 or any(matching[0].get(key) != value for key, value in row["observed"].items()):
                raise BuildError(f"CROSS_SEED_PREREQUISITE_FLOW_DRIFT {row['role']}")
            return
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field in ("seed_id", "version"):
            expected = provided["seed_version"] if field == "version" else provided["seed_id"]
            if manifest.get(field) != expected:
                raise BuildError(
                    f"CROSS_SEED_PREREQUISITE_IDENTITY {row['role']} {field}={manifest.get(field)}"
                )
        pinned = str((manifest.get("content_pins") or {}).get("bundle_content_sha256") or "")
        if pinned != provided["bundle_content_sha256"]:
            raise BuildError(
                f"CROSS_SEED_PREREQUISITE_PIN_DRIFT {row['role']} "
                f"seed={pinned} declared={provided['bundle_content_sha256']}"
            )

    def check_graph_contract(self) -> None:
        node_ids = {node["id"] for node in self.graph["nodes"]}
        for node in self.graph["nodes"]:
            for field in ("id", "node_kind", "mode", "process_uuid", "name", "location", "reference_product"):
                if not node.get(field):
                    raise BuildError(f"NODE_FIELD_MISSING {node.get('id')}/{field}")
            if node["mode"] not in {"balanced", "normalized"}:
                raise BuildError(f"NODE_MODE_INVALID {node['id']}")
            if node["node_kind"] not in {"unit_process", "market_process", "lci_dataset", "pts_module"}:
                raise BuildError(f"NODE_KIND_INVALID {node['id']}")
            for port in node["inputs"] + node["outputs"]:
                for field in ("id", "flowUuid", "name", "unit", "amount", "type", "direction"):
                    if field not in port:
                        raise BuildError(f"PORT_FIELD_MISSING {node['id']}/{port.get('id')}/{field}")
                if port["type"] not in {"technosphere", "biosphere"}:
                    raise BuildError(f"PORT_TYPE_INVALID {node['id']}/{port['id']}")
                if port["direction"] not in {"input", "output"}:
                    raise BuildError(f"PORT_DIRECTION_INVALID {node['id']}/{port['id']}")
                if port["type"] == "biosphere":
                    for field in ELEMENTARY_PORT_IDENTITY_FIELDS:
                        if not port.get(field):
                            raise BuildError(
                                f"ELEMENTARY_PORT_IDENTITY_MISSING {node['id']}/{port['id']}/{field}"
                            )
                if port["type"] == "technosphere":
                    for field in TECHNOSPHERE_PORT_IDENTITY_FIELDS:
                        if not port.get(field):
                            raise BuildError(
                                f"TECHNOSPHERE_PORT_IDENTITY_MISSING {node['id']}/{port['id']}/{field}"
                            )
        ports = {port["_exchange_id"]: port for port in self.graph_ports()}
        for edge in self.graph["exchanges"]:
            for field in ("id", "fromNode", "toNode", "sourcePortId", "targetPortId", "flowUuid", "quantityMode", "amount", "unit", "type"):
                if field not in edge:
                    raise BuildError(f"EDGE_FIELD_MISSING {edge.get('id')}/{field}")
            if edge["fromNode"] not in node_ids or edge["toNode"] not in node_ids:
                raise BuildError(f"EDGE_ENDPOINT_UNKNOWN {edge['id']}")
            source = ports.get(f'{edge["fromNode"]}::{edge["sourcePortId"]}')
            target = ports.get(f'{edge["toNode"]}::{edge["targetPortId"]}')
            if source is None or target is None:
                raise BuildError(f"EDGE_PORT_UNKNOWN {edge['id']}")
            for port in (source, target):
                if port["flowUuid"] != edge["flowUuid"]:
                    raise BuildError(f"EDGE_FLOW_IDENTITY_MISMATCH {edge['id']}")
                if port["unit"] != edge["unit"]:
                    raise BuildError(f"EDGE_UNIT_MISMATCH {edge['id']}")
            if source["direction"] != "output" or target["direction"] != "input":
                raise BuildError(f"EDGE_PORT_DIRECTION {edge['id']}")
            amount = dec(edge["amount"])
            if edge["quantityMode"] == "single":
                if dec(edge["providerAmount"]) != amount or dec(edge["consumerAmount"]) != amount:
                    raise BuildError(f"EDGE_SINGLE_QUANTITY_CONFLICT {edge['id']}")
            if dec(source["amount"]) != amount or dec(target["amount"]) != amount:
                raise BuildError(f"EDGE_AMOUNT_MISMATCH {edge['id']}")
        if not self.graph["metadata"].get("reference_exchange_id"):
            raise BuildError("REFERENCE_EXCHANGE_MISSING")
        reference = self.graph["metadata"]["reference_exchange_id"]
        if reference not in ports:
            raise BuildError(f"REFERENCE_EXCHANGE_UNKNOWN {reference}")
        if not ports[reference].get("isProduct"):
            raise BuildError("REFERENCE_EXCHANGE_NOT_PRODUCT")

    def check_elementary_identity(self) -> None:
        """A biosphere port is only solvable if it carries its own exact dataset identity."""
        ports = {
            port["_exchange_id"]: port
            for port in self.graph_ports()
            if port["type"] == "biosphere"
        }
        refs = self.graph["metadata"].get("elementary_flow_refs")
        if not isinstance(refs, list) or not refs:
            raise BuildError("ELEMENTARY_REFS_MISSING")
        if {str(ref.get("exchange_id") or "") for ref in refs} != set(ports):
            raise BuildError(
                "ELEMENTARY_REFS_EXCHANGE_SET "
                f"refs={sorted(str(ref.get('exchange_id') or '') for ref in refs)} ports={sorted(ports)}"
            )
        for ref in refs:
            exchange_id = str(ref.get("exchange_id") or "")
            missing = [field for field in ELEMENTARY_REF_REQUIRED_FIELDS if not ref.get(field)]
            if missing:
                raise BuildError(f"ELEMENTARY_REF_INCOMPLETE {exchange_id}/{missing}")
            port = ports[exchange_id]
            for field, port_field in ELEMENTARY_REF_TO_PORT.items():
                if str(ref[field]) != str(port[port_field]):
                    raise BuildError(
                        f"ELEMENTARY_REF_MISMATCH {exchange_id}/{field} ref={ref[field]} port={port[port_field]}"
                    )
        for row in self.flow_dependencies["dependencies"]:
            if row["disposition"] != "verify_present":
                continue
            used_on = [
                port for port in ports.values() if port["flowUuid"] == row["flow_uuid"]
            ]
            if not used_on:
                continue
            resolved = row.get("resolved_identity")
            if not isinstance(resolved, dict):
                raise BuildError(f"ELEMENTARY_IDENTITY_UNRESOLVED {row['role']}")
            for field in ("source_namespace", "version", "flow_property_uuid", "flow_property_version"):
                if not resolved.get(field):
                    raise BuildError(f"ELEMENTARY_RESOLVED_FIELD_MISSING {row['role']}/{field}")
            for port in used_on:
                if port["flowSourceNamespace"] != resolved["source_namespace"]:
                    raise BuildError(f"ELEMENTARY_PORT_NAMESPACE {port['_exchange_id']}")
                if port["flowVersion"] != resolved["version"]:
                    raise BuildError(f"ELEMENTARY_PORT_VERSION {port['_exchange_id']}")
                if port["flowPropertyUuid"] != resolved["flow_property_uuid"]:
                    raise BuildError(f"ELEMENTARY_PORT_FLOW_PROPERTY {port['_exchange_id']}")
                if port["flowPropertyVersion"] != resolved["flow_property_version"]:
                    raise BuildError(f"ELEMENTARY_PORT_FLOW_PROPERTY_VERSION {port['_exchange_id']}")
            for field in ("resolved_via", "resolved_at", "engine_database", "content_hash"):
                if not resolved.get(field):
                    raise BuildError(f"ELEMENTARY_RESOLVED_PROVENANCE_MISSING {row['role']}/{field}")

    def check_technosphere_identity(self) -> None:
        """One solves through an inline_snapshot, so the engine reads technosphere flow
        identity from the graph itself: docs/STANDARD_LCA_SEED_PACKAGE_V1.md section 5.2."""
        ports = {
            port["_exchange_id"]: port
            for port in self.graph_ports()
            if port["type"] == "technosphere"
        }
        declared = self.flow_dependencies.get("technosphere_identity")
        if not isinstance(declared, dict):
            raise BuildError("TECHNOSPHERE_IDENTITY_BLOCK_MISSING")
        bases = declared.get("bases")
        port_bases = declared.get("ports")
        if not isinstance(bases, dict) or not isinstance(port_bases, dict):
            raise BuildError("TECHNOSPHERE_IDENTITY_BLOCK_INCOMPLETE")
        if set(port_bases) != set(ports):
            raise BuildError(
                "TECHNOSPHERE_IDENTITY_PORT_SET "
                f"undeclared={sorted(set(ports) - set(port_bases))} "
                f"unknown={sorted(set(port_bases) - set(ports))}"
            )
        registered_gaps = {str(gap["id"]) for gap in self.clause_mapping["gaps"]}
        for name, base in sorted(bases.items()):
            for field in TECHNOSPHERE_BASIS_REQUIRED_FIELDS:
                if base.get(field) in (None, ""):
                    raise BuildError(f"TECHNOSPHERE_BASIS_FIELD_MISSING {name}/{field}")
            if not isinstance(base["attestable_on_current_engine"], bool):
                raise BuildError(f"TECHNOSPHERE_BASIS_ATTESTATION_INVALID {name}")
            if not base["attestable_on_current_engine"]:
                gap_ref = str(base.get("gap_ref") or "")
                if gap_ref not in registered_gaps:
                    raise BuildError(
                        f"TECHNOSPHERE_BASIS_GAP_UNREGISTERED {name} gap_ref={gap_ref or 'none'}"
                    )
        for exchange_id, port in sorted(ports.items()):
            base_name = str(port_bases[exchange_id])
            base = bases.get(base_name)
            if not isinstance(base, dict):
                raise BuildError(f"TECHNOSPHERE_BASIS_UNKNOWN {exchange_id} basis={base_name}")
            for field, port_field in TECHNOSPHERE_BASIS_TO_PORT.items():
                if str(port[port_field]) != str(base[field]):
                    raise BuildError(
                        f"TECHNOSPHERE_BASIS_MISMATCH {exchange_id}/{port_field} "
                        f"port={port[port_field]} basis={base[field]}"
                    )

    # ---------- method package layer ----------

    def method_packages(self) -> dict[str, dict]:
        if self._method_packages is None:
            self._method_packages = self.check_method_packages()
        return self._method_packages

    def cbam_method_package_ref(self) -> str:
        return next(
            ref
            for ref, package in sorted(self.method_packages().items())
            if package["package_kind"] == CBAM_PACKAGE_KIND
        )

    def check_method_packages(self) -> dict[str, dict]:
        references = self.manifest.get("method_package_refs")
        if not isinstance(references, list):
            raise BuildError("METHOD_PACKAGE_REFS_NOT_A_LIST")
        packages: dict[str, dict] = {}
        for entry in references:
            if not isinstance(entry, dict):
                raise BuildError(f"METHOD_PACKAGE_REF_NOT_AN_OBJECT {entry}")
            path = str(entry.get("path") or "")
            ref = f"{entry.get('package_id')}@{entry.get('version')}"
            if ref in packages:
                raise BuildError(f"METHOD_PACKAGE_REF_DUPLICATE {ref}")
            if not path.startswith(f"{METHOD_PACKAGE_DIR}/") or ".." in path:
                raise BuildError(f"METHOD_PACKAGE_REF_PATH {ref} path={path}")
            try:
                payload = self.read(path)
                registered = MethodPackageCreate(**payload).model_dump(mode="json")
            except (BuildError, ValueError) as error:
                raise BuildError(f"METHOD_PACKAGE_UNREGISTERABLE {ref} {error}") from error
            for field in PACKAGE_IDENTITY_FIELDS:
                if entry.get(field) != registered[field]:
                    raise BuildError(
                        f"METHOD_PACKAGE_REF_MISMATCH {ref}/{field} "
                        f"declared={entry.get(field)} file={registered[field]}"
                    )
            # the registry hashes the create document, so a package that carries a top-level
            # field the create model drops would have two different identities
            if canonical_json_sha256(payload) != canonical_json_sha256(registered):
                raise BuildError(f"METHOD_PACKAGE_IDENTITY_SPLIT {ref}")
            declared_hash = str(entry.get("content_sha256") or "")
            if declared_hash != canonical_json_sha256(registered):
                raise BuildError(
                    f"METHOD_PACKAGE_HASH_MISMATCH {ref} "
                    f"declared={declared_hash} computed={canonical_json_sha256(registered)}"
                )
            packages[ref] = {**registered, "path": path}
        named = {str(package["path"]) for package in packages.values()}
        for path in sorted((self.dir / METHOD_PACKAGE_DIR).glob("*.json")):
            relative = f"{METHOD_PACKAGE_DIR}/{path.name}"
            if relative not in named:
                raise BuildError(f"METHOD_PACKAGE_UNREFERENCED {relative}")
        cbam_refs = sorted(
            ref for ref, package in packages.items()
            if package["package_kind"] == CBAM_PACKAGE_KIND
        )
        if len(cbam_refs) != 1:
            raise BuildError(f"CBAM_METHOD_PACKAGE_REF_COUNT found={cbam_refs}")
        self._check_cbam_package(cbam_refs[0], packages[cbam_refs[0]])
        return packages

    def _package_port_identity(self, exchange_id: str) -> dict:
        node_id, _, port_id = exchange_id.partition("::")
        node = next((item for item in self.graph["nodes"] if item["id"] == node_id), None)
        port = (
            next(
                (item for item in node["inputs"] + node["outputs"] if item["id"] == port_id),
                None,
            )
            if node
            else None
        )
        if port is None:
            raise BuildError(f"CBAM_METHOD_PACKAGE_PORT_UNKNOWN {exchange_id}")
        identity = {field: port.get(key) for field, key in PORT_KEYS.items()}
        identity["process_uuid"] = node["process_uuid"]
        if port["type"] != "biosphere":
            identity["compartment"] = None
            return identity
        reference = next(
            (
                ref
                for ref in self.graph["metadata"].get("elementary_flow_refs") or []
                if str(ref.get("exchange_id")) == exchange_id
            ),
            None,
        )
        if reference is None:
            raise BuildError(f"CBAM_METHOD_PACKAGE_ELEMENTARY_REF_MISSING {exchange_id}")
        identity["compartment"] = reference.get("compartment")
        return identity

    def _check_cbam_package(self, ref: str, package: dict) -> None:
        manifest = package["manifest"]
        boundary = self.boundaries["cbam"]
        if (manifest.get("output_schema") or {}).get("schema_version") != CBAM_TRIAL_V2_SCHEMA:
            raise BuildError(f"CBAM_METHOD_PACKAGE_SCHEMA {ref}")
        schema = manifest.get("boundary_schema") or {}
        if schema.get("application") != boundary["application"]:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_APPLICATION {ref} "
                f"package={schema.get('application')} ledger={boundary['application']}"
            )
        segments = [
            segment
            for segment in (boundary.get("segments") or {}).values()
            if isinstance(segment, dict)
        ]

        def process_of(exchange_id: str) -> str:
            role = str(exchange_id).partition("::")[0]
            process_uuid = self.identity["process_uuids"].get(role)
            if process_uuid is None:
                raise BuildError(f"CBAM_METHOD_PACKAGE_PROCESS_UNKNOWN {ref} {role}")
            return str(process_uuid)

        classified = [
            entry
            for segment in segments
            for entry in (segment.get("included_exchanges") or [])
            + (segment.get("excluded_exchanges") or [])
        ] + list(boundary.get("not_applicable") or [])
        in_boundary = sorted({process_of(str(entry["exchange_id"])) for entry in classified})
        reference_exchange_id = str(self.graph["metadata"].get("reference_exchange_id") or "")
        # the denominator owner is the model's own reference exchange, which is also the port
        # whose product rule the package must restate below
        reference_process_uuid = str(
            self._package_port_identity(reference_exchange_id)["process_uuid"]
        )
        expected_boundary = {
            "schema": MULTI_PROCESS_BOUNDARY_SCHEMA,
            "reference_process_uuid": reference_process_uuid,
            "in_boundary_process_uuids": in_boundary,
            "clause": boundary["goods_identity"]["route_boundary_clause"],
        }
        declared_boundary = schema.get("production_process_boundary")
        if not isinstance(declared_boundary, dict) or {
            field: declared_boundary.get(field) for field in expected_boundary
        } != expected_boundary:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_BOUNDARY {ref} "
                f"package={declared_boundary} ledger={expected_boundary}"
            )
        rules = manifest.get("classification_rules") or {}
        emissions = rules.get("direct_emissions")
        if not isinstance(emissions, list):
            raise BuildError(f"CBAM_METHOD_PACKAGE_DIRECT_EMISSIONS_MISSING {ref}")
        calculation = str((manifest.get("formula_graph") or {}).get("calculation") or "")
        if calculation not in CBAM_CALCULATIONS:
            raise BuildError(f"CBAM_METHOD_PACKAGE_CALCULATION {ref} {calculation}")
        three_component = calculation == CBAM_THREE_COMPONENT_CALCULATION
        buckets = self.cbam_included_ids()
        components = self._check_cbam_components(ref, schema, three_component, buckets)
        self._check_cbam_precursors(ref, schema, manifest, boundary, buckets, three_component)
        self._check_cbam_nitrogen(ref, schema, manifest, three_component)
        gases = [str(gas) for gas in boundary["goods_identity"]["greenhouse_gases"]]
        counted_ids = sorted(
            str(entry["exchange_id"])
            for segment in segments
            if segment.get("conclusion") not in NON_DIRECT_CONCLUSIONS
            for entry in (segment.get("included_exchanges") or [])
        )
        if sorted(str(entry.get("exchange_id")) for entry in emissions) != counted_ids:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_COUNT_MISMATCH {ref} "
                f"package={sorted(str(entry.get('exchange_id')) for entry in emissions)} "
                f"ledger={counted_ids}"
            )
        for entry in emissions:
            self._check_package_rule(
                ref, str(entry.get("exchange_id") or ""), entry, allowed_gases=gases
            )
        product = rules.get("product") or {}
        if str(product.get("reference_exchange_id") or "") != reference_exchange_id:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_REFERENCE_EXCHANGE {ref} "
                f"package={product.get('reference_exchange_id')} graph={reference_exchange_id}"
            )
        self._check_package_rule(ref, reference_exchange_id, product, allowed_gases=gases)
        end_use = schema.get("end_use") or {}
        pending = {
            str(item["clause"])
            for item in boundary.get("undecided") or []
            if item.get("runtime_input_required")
        }
        values = end_use.get("values")
        if pending:
            if end_use.get("clause") not in pending or not values:
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_END_USE {ref} clause={end_use.get('clause')} "
                    f"undecided={sorted(pending)}"
                )
            if not set(end_use.get("not_a_cbam_good") or []) <= set(values):
                raise BuildError(f"CBAM_METHOD_PACKAGE_END_USE_VALUES {ref}")
        elif not (
            end_use.get("state") == NO_RUNTIME_DECLARATION_STATE
            and self.clause_pattern.search(str(end_use.get("clause") or ""))
        ):
            # a good with no end-use gate must say so: omitting end_use and having nothing to
            # declare are indistinguishable in data, which is how coverage goes missing
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_END_USE {ref} state={end_use.get('state')} "
                f"undecided={sorted(pending)} required={NO_RUNTIME_DECLARATION_STATE}"
            )
        self._check_rule_source(ref, manifest)
        self._check_cbam_expected(ref, manifest, components, three_component)

    def _cited_file(
        self, ref: str, code: str, pointer: object, *, need_fragment: bool = True
    ) -> tuple[Path, str]:
        """Resolve one `path#dot.pointer` citation onto a file this seed declares as its own.

        The match is a suffix against the manifest's authorable list rather than a prefix against
        the repository root, because the seed directory is renamed when it is staged or copied for
        an install validation, and a citation that only resolves in one checkout would refuse a
        seed whose bytes are unchanged. The cost is that a citation may not name a file outside
        this seed, which is the point: an out-of-tree citation cannot be reopened from the bundle.
        """
        path_text, _, fragment = str(pointer or "").partition("#")
        if not path_text or (need_fragment and not fragment):
            raise BuildError(f"{code} {ref} {pointer}")
        wanted = PurePosixPath(path_text).parts
        authorable = (self.manifest.get("files") or {}).get("authorable") or []
        matches = [
            relative
            for relative in authorable
            if PurePosixPath(relative).parts == wanted[-len(PurePosixPath(relative).parts) :]
        ]
        if len(matches) != 1:
            raise BuildError(f"{code} {ref} {pointer} authorable_matches={matches}")
        path = (self.dir / matches[0]).resolve()
        if self.dir.resolve() not in path.parents or not path.is_file():
            raise BuildError(f"{code} {ref} {pointer}")
        return path, fragment

    def _check_rule_source(self, ref: str, manifest: dict) -> None:
        """The v2 trial verifies `provenance.rule_source` by hashing it back onto itself, so the
        builder has to reproduce that check or it ships a package that installs and then refuses."""
        source = (manifest.get("provenance") or {}).get("rule_source")
        if not isinstance(source, dict):
            raise BuildError(f"CBAM_METHOD_PACKAGE_RULE_SOURCE_MISSING {ref}")
        self._cited_file(
            ref,
            "CBAM_METHOD_PACKAGE_RULE_SOURCE_EVIDENCE",
            source.get("evidence_ref"),
            need_fragment=False,
        )
        declared = str(source.get("content_sha256") or "")
        basis = {key: value for key, value in source.items() if key != "content_sha256"}
        computed = canonical_json_sha256(basis)
        if not declared or declared != computed:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_RULE_SOURCE_HASH {ref} declared={declared} computed={computed}"
            )

    def _check_cbam_nitrogen(
        self, ref: str, schema: dict, manifest: dict, three_component: bool
    ) -> None:
        """The runtime reads the legal denominator out of the package alone, so the package's copy
        is compared field by field with the seed's own parameter record at build time.

        A drift here is not cosmetic: the per-kilogram-nitrogen result would be computed from a
        number no authored file in the bundle carries, which is the frontend-constant defect the
        parameter record exists to refuse.
        """
        declared = schema.get("nitrogen_basis")
        nitrogen = self.parameters.get("nitrogen")
        if declared is None:
            if nitrogen is not None:
                raise BuildError(f"CBAM_METHOD_PACKAGE_NITROGEN_UNPUBLISHED {ref}")
            return
        if nitrogen is None or not isinstance(declared, dict):
            raise BuildError(f"CBAM_METHOD_PACKAGE_NITROGEN_NO_PARAMETER {ref}")
        drifted: dict[str, dict] = {}
        content = declared.get("content_of_n")
        if not isinstance(content, dict):
            raise BuildError(f"CBAM_METHOD_PACKAGE_NITROGEN_CONTENT_MISSING {ref}")
        for field in NITROGEN_CONTENT_FIELDS:
            if field not in content or content[field] != nitrogen[field]:
                drifted[f"content_of_n.{field}"] = {
                    "package": content.get(field),
                    "parameter": nitrogen.get(field),
                }
        if content.get("parameter_ref") != self.profile["parameter_files"]["nitrogen"]:
            drifted["content_of_n.parameter_ref"] = {
                "package": content.get("parameter_ref"),
                "parameter": self.profile["parameter_files"]["nitrogen"],
            }
        if not str(content.get("derivation_route") or ""):
            drifted["content_of_n.derivation_route"] = {"package": None, "parameter": "required"}
        published = str(content.get("published_source_sha256") or "")
        if published != str((nitrogen.get("published_source") or {}).get("content_sha256") or ""):
            drifted["content_of_n.published_source_sha256"] = {
                "package": published,
                "parameter": (nitrogen.get("published_source") or {}).get("content_sha256"),
            }
        if [str(code) for code in declared.get("applicable_cn_codes") or []] != [
            str(code) for code in nitrogen.get("applicable_cn_codes") or []
        ]:
            drifted["applicable_cn_codes"] = {
                "package": declared.get("applicable_cn_codes"),
                "parameter": nitrogen.get("applicable_cn_codes"),
            }
        if (declared.get("composition_adjustment") or {}).get("applied") != (
            nitrogen.get("composition_adjustment") or {}
        ).get("applied"):
            drifted["composition_adjustment.applied"] = {
                "package": (declared.get("composition_adjustment") or {}).get("applied"),
                "parameter": (nitrogen.get("composition_adjustment") or {}).get("applied"),
            }
        ledger = self.expected["nitrogen_basis"]
        # the acceptance ledger prints its unit with spaces around the slash while the machine unit
        # string has none, so the comparison is on the spelling with display spacing removed
        if str(declared.get("metric") or "").replace(" ", "") != str(
            ledger.get("unit") or ""
        ).replace(" ", ""):
            drifted["metric"] = {
                "package": declared.get("metric"),
                "acceptance": ledger.get("unit"),
            }
        for name in ("per_tonne_product", "per_kg_n"):
            if (declared.get("labels") or {}).get(name) != (ledger.get(name) or {}).get("label"):
                drifted[f"labels.{name}"] = {
                    "package": (declared.get("labels") or {}).get(name),
                    "acceptance": (ledger.get(name) or {}).get("label"),
                }
        if drifted:
            raise BuildError(f"CBAM_METHOD_PACKAGE_NITROGEN_PARAMETER {ref} {drifted}")
        cn_code = str(self.boundaries["cbam"]["goods_identity"]["cn_code"])
        if declared.get("applies") is not True or cn_code not in [
            str(code) for code in declared.get("applicable_cn_codes") or []
        ]:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_NITROGEN_BASIS_NOT_APPLICABLE {ref} cn_code={cn_code}"
            )
        for source in (manifest.get("precursor_rules") or {}).get("sources") or []:
            basis = source.get("mass_floor_basis") if isinstance(source, dict) else None
            if basis is not None and (
                basis not in MASS_FLOOR_BASES or not three_component
            ):
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_MASS_FLOOR_BASIS {ref} {basis} "
                    f"three_component={three_component}"
                )
        self._check_cbam_loss_links(ref, manifest, three_component)

    def _check_cbam_loss_links(self, ref: str, manifest: dict, three_component: bool) -> None:
        """Prove that the loss streams inside a precursor's total demand are the boundary's own.

        A-C16 counts the precursor on the quantity fed to the process, and the stream cut off from
        it is a different flow, so the package has to name which loss ports belong to which source.
        The names are checked against the boundary ledger rather than trusted, and every loss port
        of the ledger has to be claimed by some source: an unclaimed one would drop out of the mass
        floor silently, which is the coverage hole this slice refuses to ship.
        """
        sources = [
            source
            for source in (manifest.get("precursor_rules") or {}).get("sources") or []
            if isinstance(source, dict)
        ]
        losses = sorted(
            str(entry.get("exchange_id") or "")
            for entry in self.boundaries["cbam"].get("not_applicable") or []
            if isinstance(entry, dict)
            and entry.get("disposition") == LOSS_DISPOSITION
        )
        claimed: dict[str, str] = {}
        for source in sources:
            named = source.get("loss_exchange_ids") or []
            if not isinstance(named, list):
                raise BuildError(f"CBAM_METHOD_PACKAGE_LOSS_LINKS {ref} {named}")
            if named and not source.get("mass_floor_basis"):
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_LOSS_LINK_WITHOUT_FLOOR {ref} "
                    f"flow_uuid={source.get('flow_uuid')} named={len(named)}"
                )
            flow_uuid = str(source.get("flow_uuid"))
            for exchange_id in named:
                if str(exchange_id) not in losses:
                    raise BuildError(
                        f"CBAM_METHOD_PACKAGE_LOSS_LINK_NOT_A_LOSS_PORT {ref} {exchange_id} "
                        f"ledger={losses}"
                    )
                claimed[str(exchange_id)] = flow_uuid
        missing = sorted(set(losses) - set(claimed))
        if three_component and missing:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_LOSS_STREAM_UNOWNED {ref} {missing} claimed={sorted(claimed)}"
            )

    def _check_cbam_components(
        self, ref: str, schema: dict, three_component: bool, buckets: dict[str, set]
    ) -> dict:
        """A three component package declares which of its three components the law asks for, and
        the ledger's buckets decide whether that declaration can carry a number."""
        declared = schema.get("emission_components")
        if not three_component:
            if declared is not None:
                raise BuildError(f"CBAM_METHOD_PACKAGE_COMPONENT_PROFILE {ref}")
            return {}
        if not isinstance(declared, dict) or sorted(declared) != sorted(CBAM_COMPONENTS):
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_COMPONENTS {ref} "
                f"declared={sorted(declared) if isinstance(declared, dict) else declared}"
            )
        for name in CBAM_COMPONENTS:
            row = declared[name]
            if not isinstance(row, dict):
                raise BuildError(f"CBAM_METHOD_PACKAGE_COMPONENTS {ref} {name} {row}")
            status = row.get("status")
            if status not in CBAM_COMPONENT_STATUSES:
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_COMPONENT_STATUS {ref} {name} status={status}"
                )
            if not self.clause_pattern.search(str(row.get("clause") or "")):
                raise BuildError(f"CBAM_METHOD_PACKAGE_COMPONENT_CLAUSE {ref} {name}")
            ports = sorted(buckets[CBAM_COMPONENT_BUCKETS[name]])
            if (status == "applicable") != bool(ports):
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_COMPONENT_MISMATCH {ref} {name} "
                    f"status={status} ledger_ports={ports}"
                )
            if status != "applicable" and not str(row.get("basis") or ""):
                raise BuildError(f"CBAM_METHOD_PACKAGE_COMPONENT_BASIS {ref} {name}")
        return declared

    def _check_cbam_precursors(
        self,
        ref: str,
        schema: dict,
        manifest: dict,
        boundary: dict,
        buckets: dict[str, set],
        three_component: bool,
    ) -> None:
        """Restate the ledger's Annex I membership records and pin where a precursor came from."""
        rules = manifest.get("precursor_rules")
        if not isinstance(rules, dict):
            raise BuildError(f"CBAM_METHOD_PACKAGE_PRECURSOR_RULES_MISSING {ref}")
        evidence = rules.get("membership_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise BuildError(f"CBAM_METHOD_PACKAGE_MEMBERSHIP_MISSING {ref}")
        by_flow: dict[str, dict] = {}
        for row in evidence:
            flow_uuid = str(row.get("flow_uuid") or "") if isinstance(row, dict) else ""
            if not flow_uuid or flow_uuid in by_flow:
                raise BuildError(f"CBAM_METHOD_PACKAGE_MEMBERSHIP_FLOW {ref} {flow_uuid or row}")
            by_flow[flow_uuid] = row
        port_flows = {
            str(port.get("flowUuid") or "")
            for node in self.graph["nodes"]
            for port in node["inputs"] + node["outputs"]
        }
        if unknown := sorted(set(by_flow) - port_flows):
            raise BuildError(f"CBAM_METHOD_PACKAGE_MEMBERSHIP_UNKNOWN_FLOW {ref} {unknown}")
        flows_of_role = {
            str(row["role"]): str(row["flow_uuid"])
            for row in self.flow_dependencies["dependencies"]
        }
        declared_by_flow: dict[str, dict] = {}
        for segment in self.cbam_segments():
            for entry in segment.get("checked_inputs") or []:
                if not isinstance(entry, dict) or entry.get("membership") is None:
                    if three_component:
                        raise BuildError(
                            f"CBAM_METHOD_PACKAGE_MEMBERSHIP_STATE {ref} {entry}"
                        )
                    continue
                role = str(entry.get("flow_role") or "")
                if role not in flows_of_role:
                    raise BuildError(f"CBAM_METHOD_PACKAGE_MEMBERSHIP_FLOW_UNKNOWN {ref} {role}")
                flow_uuid = flows_of_role[role]
                if flow_uuid in declared_by_flow:
                    raise BuildError(
                        f"CBAM_METHOD_PACKAGE_MEMBERSHIP_STATE {ref} {role} declared twice"
                    )
                declared_by_flow[flow_uuid] = entry
        for flow_uuid, entry in sorted(declared_by_flow.items()):
            row = by_flow.get(flow_uuid)
            if row is None:
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_MEMBERSHIP_MISSING {ref} "
                    f"{entry.get('flow_role')} flow_uuid={flow_uuid}"
                )
            drifted = {
                field: {"package": row.get(field), "ledger": entry.get(field)}
                for field in ("membership", "annex_i_listed", "clause")
                if row.get(field) != entry.get(field)
            }
            governed = row.get("governing_clause")
            if (entry.get("membership") == "listed_governed_elsewhere") != bool(governed):
                drifted["governing_clause"] = governed
            elif governed and not self.clause_pattern.search(str(governed)):
                drifted["governing_clause"] = governed
            if drifted:
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_MEMBERSHIP_MISMATCH {ref} {flow_uuid} {drifted}"
                )
        complex_good = any(
            str(row.get("membership")) == "listed_precursor" for row in by_flow.values()
        )
        expected_complexity = "complex" if complex_good else "simple"
        ledger_complexity = str(boundary["goods_identity"].get("goods_complexity") or "")
        if schema.get("goods_complexity") != expected_complexity:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_GOODS_COMPLEXITY {ref} "
                f"package={schema.get('goods_complexity')} membership={expected_complexity}"
            )
        if ledger_complexity != expected_complexity:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_GOODS_COMPLEXITY {ref} "
                f"ledger={ledger_complexity} membership={expected_complexity}"
            )
        precursor_flows = {
            str(self._package_port_identity(exchange_id)["flow_uuid"])
            for exchange_id in buckets["precursor"]
        }
        sources = rules.get("sources") or []
        if not isinstance(sources, list):
            raise BuildError(f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCES {ref}")
        if {str(row.get("flow_uuid") or "") for row in sources if isinstance(row, dict)} != (
            precursor_flows
        ):
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCES {ref} "
                f"package={sorted(str(row.get('flow_uuid')) for row in sources)} "
                f"ledger={sorted(precursor_flows)}"
            )
        if not sources:
            return
        attribution = next(
            (
                segment.get("attribution")
                for segment in self.cbam_segments()
                if segment.get("conclusion") == PRECURSOR_CONCLUSION
            ),
            None,
        )
        own_processes = {str(uuid) for uuid in self.identity["process_uuids"].values()}
        for row in sources:
            self._check_package_precursor_source(ref, row, attribution, own_processes)

    def _check_package_precursor_source(
        self, ref: str, row: dict, attribution: object, own_processes: set[str]
    ) -> None:
        """A precursor's emissions may only enter this result through one named release of one
        seed, so the pin is read back out of that seed's own manifest and the acceptance ledger."""
        if not isinstance(row, dict):
            raise BuildError(f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCES {ref} {row}")
        package_ref = str(row.get("method_package_ref") or "")
        if not EXACT_PACKAGE_REF.match(package_ref):
            raise BuildError(f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_REF {ref} {package_ref}")
        if row.get("attribution") != attribution:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_ATTRIBUTION {ref} "
                f"package={row.get('attribution')} ledger={attribution}"
            )
        if not self.clause_pattern.search(str(row.get("clause") or "")):
            raise BuildError(f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_CLAUSE {ref} {package_ref}")
        if str(row.get("source_process_uuid") or "") in own_processes:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_INSIDE {ref} "
                f"{row.get('source_process_uuid')}"
            )
        ledger = next(
            (
                item
                for item in self.expected["cbam"]["functional_unit_result"][
                    "emission_components"
                ]
                if str(item.get("component")) == "precursor_mass"
            ),
            None,
        )
        source = (ledger or {}).get("source") or {}
        drifted = {
            field: {"package": row.get(package_field), "acceptance": source.get(field)}
            for field, package_field in SOURCE_PIN_FIELDS.items()
            if row.get(package_field) != source.get(field)
        }
        if drifted:
            raise BuildError(f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_PIN {ref} {drifted}")
        directory = str(source.get("seed_directory") or "")
        manifest_path = REPO_ROOT / "cases" / "standard-lca-seeds" / directory / "seed.json"
        if not directory or not manifest_path.is_file():
            raise BuildError(f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_SEED {ref} {directory}")
        document = self._load_document(manifest_path)
        if document.get("seed_id") != source.get("seed_id"):
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_SEED {ref} {directory}"
            )
        if document.get("version") != source.get("seed_version"):
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_VERSION {ref} "
                f"{directory}={document.get('version')} pinned={source.get('seed_version')}"
            )
        pinned_bundle = str(
            (document.get("content_pins") or {}).get("bundle_content_sha256") or ""
        )
        if pinned_bundle != source.get("bundle_content_sha256"):
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_BUNDLE_PIN {ref} "
                f"seed={pinned_bundle} pinned={source.get('bundle_content_sha256')}"
            )
        entry = next(
            (
                item
                for item in document.get("method_package_refs") or []
                if f"{item.get('package_id')}@{item.get('version')}" == package_ref
            ),
            None,
        )
        if entry is None:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_PACKAGE {ref} {package_ref}"
            )
        if entry.get("content_sha256") != source.get("package_content_sha256"):
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_PACKAGE_PIN {ref} {package_ref} "
                f"seed={entry.get('content_sha256')} pinned="
                f"{source.get('package_content_sha256')}"
            )
        if str(row.get("source_process_uuid") or "") not in {
            str(uuid) for uuid in (document.get("identity") or {}).get("process_uuids", {}).values()
        }:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_PRECURSOR_SOURCE_PROCESS {ref} "
                f"{package_ref} {row.get('source_process_uuid')}"
            )

    def _load_document(self, path: Path) -> dict:
        if path not in self._documents:
            self._documents[path] = json.loads(path.read_text(encoding="utf-8"))
        return self._documents[path]

    def _expected_at(self, ref: str, source: object):
        """Read one value out of the seed's own acceptance ledger: the package restates the number,
        it does not own it, so the pointer is resolved and compared rather than left as a comment."""
        path, fragment = self._cited_file(
            ref, "CBAM_METHOD_PACKAGE_EXPECTED_SOURCE_PATH", source
        )
        node: object = self._load_document(path)
        for token in fragment.split("."):
            name, _, selector = token.partition("[")
            if name:
                if not isinstance(node, dict) or name not in node:
                    raise BuildError(
                        f"CBAM_METHOD_PACKAGE_EXPECTED_SOURCE_UNRESOLVED {ref} {source} {name}"
                    )
                node = node[name]
            if selector:
                field, _, wanted = selector.rstrip("]").partition("=")
                rows = (
                    [row for row in node if isinstance(row, dict) and str(row.get(field)) == wanted]
                    if isinstance(node, list)
                    else []
                )
                if len(rows) != 1:
                    raise BuildError(
                        f"CBAM_METHOD_PACKAGE_EXPECTED_SOURCE_UNRESOLVED {ref} {source} {token}"
                    )
                node = rows[0]
        return node

    def _reference_product_activity_kg(self) -> Decimal:
        """The kilogram amount this model authors of its own reference product.

        This is the activity the runtime solves at: `cbam_trial_v2` refuses a trial whose activity
        vector differs from the scaled reference product output, so the authored port amount is
        the multiplier that turns a per-tonne ledger reading into the numerator in kg."""
        reference = str(self.graph["metadata"].get("reference_exchange_id") or "")
        port = next(
            (item for item in self.graph_ports() if item["_exchange_id"] == reference), None
        )
        if port is None:
            raise BuildError(f"CBAM_METHOD_PACKAGE_REFERENCE_PRODUCT_MISSING {reference}")
        if port.get("unit") != "kg":
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_REFERENCE_PRODUCT_UNIT {reference} unit={port.get('unit')}"
            )
        return dec(port["amount"])

    def _check_cbam_expected(
        self, ref: str, manifest: dict, components: dict, three_component: bool
    ) -> None:
        rules = manifest.get("validation_rules") or {}
        legacy = rules.get("expected_direct_emissions_kg")
        declared = rules.get("expected_result")
        result = self.expected["cbam"]["functional_unit_result"]
        if not three_component:
            if declared is not None:
                raise BuildError(f"CBAM_METHOD_PACKAGE_EXPECTED_TOTAL_KEY {ref}")
            # the runtime compares this field with the solved numerator in kg, while the ledger's
            # authored_sum is the per-tonne reading of the same mass. The two are one number only
            # for a model that authors 1 kg of product, which is the coincidence the hydrogen seed
            # hid; scale the ledger reading onto this seed's own activity before comparing.
            activity_kg = self._reference_product_activity_kg()
            expected_kg = dec(result["authored_sum"]) * activity_kg
            value = (legacy or {}).get("value")
            if dec(value or "") != expected_kg:
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_EXPECTED_TOTAL {ref} "
                    f"package={value} acceptance={result['authored_sum']} "
                    f"activity_kg={activity_kg} expected_kg={expected_kg}"
                )
            source = (legacy or {}).get("source")
            resolved = self._expected_at(ref, source)
            if dec(resolved) != expected_kg:
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_EXPECTED_TOTAL_SOURCE {ref} package={value} "
                    f"source={source} resolved={resolved} expected_kg={expected_kg}"
                )
            return
        if legacy is not None:
            raise BuildError(f"CBAM_METHOD_PACKAGE_EXPECTED_TOTAL_KEY {ref}")
        if not isinstance(declared, dict):
            raise BuildError(f"CBAM_METHOD_PACKAGE_EXPECTED_TOTAL_MISSING {ref}")
        state = "partial" if result.get("partial_result") else "complete"
        if declared.get("state") != state or declared.get("unit") != result.get("unit"):
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_EXPECTED_STATE {ref} package={declared.get('state')}/"
                f"{declared.get('unit')} acceptance={state}/{result.get('unit')}"
            )
        total = declared.get("value")
        if str(total or "") != str(result["authored_sum"]) or str(
            self._expected_at(ref, declared.get("source"))
        ) != str(total):
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_EXPECTED_TOTAL {ref} package={total} "
                f"acceptance={result['authored_sum']} source={declared.get('source')}"
            )
        parts = declared.get("components")
        if not isinstance(parts, dict) or sorted(parts) != sorted(CBAM_COMPONENTS):
            raise BuildError(f"CBAM_METHOD_PACKAGE_EXPECTED_COMPONENTS {ref} declared={parts}")
        sum_of_complete = Decimal(0)
        for name in CBAM_COMPONENTS:
            row = parts[name]
            if not isinstance(row, dict) or row.get("state") not in CBAM_EXPECTED_COMPONENT_STATES:
                raise BuildError(f"CBAM_METHOD_PACKAGE_EXPECTED_COMPONENTS {ref} {name} {row}")
            status = components[name].get("status")
            expected_state = {
                "applicable": "complete",
                "not_applicable_with_basis": "not_applicable",
            }[status]
            observed = row.get("state")
            value = row.get("value")
            resolved = self._expected_at(ref, row.get("source"))
            if observed == "complete":
                if value is None or str(resolved) != str(value):
                    raise BuildError(
                        f"CBAM_METHOD_PACKAGE_EXPECTED_VALUE {ref} {name} package={value} "
                        f"acceptance={resolved}"
                    )
                sum_of_complete += Decimal(str(value))
            elif observed == "formula_only":
                if value is not None or not str(row.get("missing") or ""):
                    raise BuildError(
                        f"CBAM_METHOD_PACKAGE_EXPECTED_VALUE {ref} {name} "
                        f"formula_only carries value={value} missing={row.get('missing')}"
                    )
                if not isinstance(resolved, dict) or resolved.get("state") != "formula_only":
                    raise BuildError(
                        f"CBAM_METHOD_PACKAGE_EXPECTED_COMPONENT_STATE {ref} {name} "
                        f"source={row.get('source')}"
                    )
            elif value is not None:
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_EXPECTED_VALUE {ref} {name} "
                    f"not_applicable carries value={value}"
                )
            if observed != expected_state and not (
                status == "applicable" and observed == "formula_only"
            ):
                # a component the law asks for is either numbered or explicitly still missing; a
                # component the law does not ask for may not carry a number at all
                raise BuildError(
                    f"CBAM_METHOD_PACKAGE_EXPECTED_COMPONENT_STATE {ref} {name} "
                    f"package={observed} components_status={status}"
                )
        if sum_of_complete != Decimal(str(total)):
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_EXPECTED_COMPONENT_SUM {ref} "
                f"complete={sum_of_complete} total={total}"
            )

    def _check_package_rule(
        self, ref: str, exchange_id: str, entry: dict, *, allowed_gases: list[str]
    ) -> None:
        expected = self._package_port_identity(exchange_id)
        drifted = {
            field: {"package": entry.get(field), "model": value}
            for field, value in expected.items()
            if entry.get(field) != value
        }
        if drifted:
            raise BuildError(f"CBAM_METHOD_PACKAGE_PORT_IDENTITY {ref} {exchange_id} {drifted}")
        declared_gas = entry.get("greenhouse_gas")
        if declared_gas is not None and str(declared_gas) not in allowed_gases:
            raise BuildError(
                f"CBAM_METHOD_PACKAGE_GAS_UNDECLARED {ref} {exchange_id} "
                f"rule={declared_gas} package={allowed_gases}"
            )

    # ---------- bundle ----------

    def version_row(self) -> dict:
        return {
            "id": self.identity["model_version_id"],
            "model_id": self.identity["project_id"],
            "version": 1,
            "graph_hash": None,
            "hybrid_graph_json": self.graph,
            "created_at": self.project_row["payload"]["created_at"],
        }

    def dependencies_entry(self) -> list[dict]:
        entries = []
        for row in self.flow_dependencies["dependencies"]:
            if row["disposition"] != "verify_present":
                continue
            resolved = row.get("resolved_identity") or {}
            source_namespace = resolved.get("source_namespace") or row["observed"].get(
                "source_namespace"
            )
            source_version = resolved.get("version") or row["observed"].get("source_version")
            entries.append(
                {
                    "kind": "flow",
                    "flow_uuid": row["flow_uuid"],
                    "source_namespace": source_namespace,
                    "source_version": source_version,
                    "reason": "seed_declared_external_identity",
                }
            )
        return entries

    def entries(self) -> dict[str, object]:
        return {
            "project.json": self.project_row["payload"],
            "versions.json": [self.version_row()],
            "runs.json": [],
            "catalog/flows.json": self.owned_flows["rows"],
            "catalog/flow_versions.json": self.flow_dependencies["bundled_catalog_columns"]["flow_versions"],
            "catalog/unit_groups.json": self.flow_dependencies["bundled_catalog_columns"]["unit_groups"],
            "catalog/unit_definitions.json": self.flow_dependencies["bundled_catalog_columns"]["unit_definitions"],
            "dependencies.json": self.dependencies_entry(),
        }

    def file_digest(self, relative: str) -> str:
        return digest((self.dir / relative).read_bytes())

    def digest_map(self, paths: list[Path]) -> dict[str, str]:
        return {path.name: digest(path.read_bytes()) for path in sorted(paths)}

    def pins(self) -> dict[str, object]:
        entry_digests = {
            name: digest(data) for name, data in sorted((self.entries_bytes()).items())
        }
        return {
            "graph_sha256": self.file_digest("model/graph.json"),
            "roles_sha256": self.file_digest("model/roles.json"),
            "flow_dependencies_sha256": self.file_digest("model/flow-dependencies.json"),
            "owned_flows_sha256": self.file_digest("model/owned-flows.json"),
            "project_row_sha256": self.file_digest("model/project-row.json"),
            "parameters_sha256": digest(canonical_bytes(self.digest_map(sorted((self.dir / "parameters").glob("*.json"))))),
            "boundaries_sha256": digest(canonical_bytes(self.digest_map(sorted((self.dir / "boundaries").glob("*.json"))))),
            "acceptance_sha256": self.file_digest("acceptance/expected-values.json"),
            "clause_mapping_sha256": self.file_digest("eu-clause-mapping.json"),
            "bundle_content_sha256": digest(canonical_bytes(entry_digests)),
        }

    def entries_bytes(self) -> dict[str, bytes]:
        return {name: canonical_bytes(value) for name, value in self.entries().items()}

    def check_pins(self) -> None:
        declared = self.manifest["content_pins"]
        computed = self.pins()
        for field in SCALAR_PINS:
            if declared.get(field) != computed[field]:
                raise BuildError(f"PIN_MISMATCH {field} declared={declared.get(field)} computed={computed[field]}")
        for field in GROUP_PINS:
            if declared.get(field) != computed[field]:
                raise BuildError(f"PIN_MISMATCH {field} declared={declared.get(field)} computed={computed[field]}")
        if self.manifest["seed_id"] != self.graph_document["seed_id"]:
            raise BuildError("SEED_ID_MISMATCH")
        if self.manifest["version"] != self.graph_document["version"]:
            raise BuildError("SEED_VERSION_MISMATCH")

    @pinned_arithmetic
    def write_pins(self) -> bool:
        self.check_content()
        path = self.dir / "seed.json"
        text = path.read_text(encoding="utf-8")
        computed = self.pins()
        for field in (*SCALAR_PINS, *GROUP_PINS):
            pattern = '"' + field + '": (?:"(?:PENDING|[0-9a-f]{64})"|\\{[^{}]*\\})'
            text, count = re.subn(pattern, f'"{field}": "{computed[field]}"', text)
            if count != 1:
                raise BuildError(f"PIN_FIELD_NOT_REWRITEABLE {field} matches={count}")
        if path.read_text(encoding="utf-8") == text:
            return False
        path.write_text(text, encoding="utf-8", newline="\n")
        return True

    @pinned_arithmetic
    def validate(self) -> None:
        self.check_content()
        self.check_pins()

    @pinned_arithmetic
    def check_content(self) -> None:
        self.check_identity()
        self.check_parameter_shapes()
        for check in self.profile["arithmetic_checks"]:
            getattr(self, f"check_{check}")()
        self.check_roles()
        self.check_boundaries()
        self.check_cbam_candidate_universe()
        self.check_flow_dependencies()
        self.check_graph_contract()
        self.check_elementary_identity()
        self.check_technosphere_identity()
        self.method_packages()

    @pinned_arithmetic
    def build(self) -> dict:
        self.validate()
        entries = self.entries_bytes()
        for name in REQUIRED_ENTRIES:
            if name not in entries:
                raise BuildError(f"BUNDLE_ENTRY_MISSING {name}")
        if len(entries) + 1 > MAX_FILES:
            raise BuildError("BUNDLE_ENTRY_COUNT_LIMIT")
        for name, data in entries.items():
            if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                raise BuildError(f"BUNDLE_UNSAFE_PATH {name}")
            if len(data) > MAX_BUNDLE_BYTES:
                raise BuildError(f"BUNDLE_ENTRY_TOO_LARGE {name}")
        def row_count(name: str) -> int:
            value = json.loads(entries[name])
            return len(value) if isinstance(value, list) else 1

        manifest = {
            "schema_version": BUNDLE_SCHEMA,
            "project_id": self.project_row["payload"]["id"],
            "project_name": self.project_row["payload"]["name"],
            "seed_id": self.seed_id,
            "seed_version": self.version,
            "content": {
                name: {"sha256": digest(data), "bytes": len(data)} for name, data in sorted(entries.items())
            },
            "counts": {
                "versions": row_count("versions.json"),
                "runs": row_count("runs.json"),
                "flows": row_count("catalog/flows.json"),
                "flow_versions": row_count("catalog/flow_versions.json"),
                "unit_groups": row_count("catalog/unit_groups.json"),
                "unit_definitions": row_count("catalog/unit_definitions.json"),
                "external_dependencies": row_count("dependencies.json"),
            },
        }
        zip_path = self.dir / "build" / f"{self.dir.name}-{self.version}.nebula.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in [("manifest.json", canonical_bytes(manifest)), *sorted(entries.items())]:
                info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, data)
        report = {
            "schema_version": "nebula.standard-seed.build-report.v1",
            "seed_id": self.seed_id,
            "seed_version": self.version,
            "bundle_content_sha256": self.pins()["bundle_content_sha256"],
            "zip_sha256": digest(zip_path.read_bytes()),
            "zip_bytes": zip_path.stat().st_size,
            "zip_path": relative_to_repo(zip_path),
            "manifest": manifest,
            "identity": self.identity,
            "graph_contract": {
                "nodes": len(self.graph["nodes"]),
                "exchanges": len(self.graph["exchanges"]),
                "reference_exchange_id": self.graph["metadata"]["reference_exchange_id"],
                "functional_unit": self.graph["functionalUnit"],
            },
            "engine_graph_hash": None,
            "engine_graph_hash_policy": "recorded from the provider snapshot at the verified stage and pinned by the install receipt; the builder does not pre-compute it, see docs/STANDARD_LCA_SEED_PACKAGE_V1.md section 6",
        }
        (self.dir / "build" / "nebula-seed-bundle.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return report


def seed_directory(name: str) -> Path:
    return REPO_ROOT / "cases" / "standard-lca-seeds" / name


def resolve_seed_directory(seed: str, seed_dir: Path | None) -> Path:
    if seed_dir is None:
        return seed_directory(seed)
    candidate = seed_dir if seed_dir.is_absolute() else REPO_ROOT / seed_dir
    return candidate
