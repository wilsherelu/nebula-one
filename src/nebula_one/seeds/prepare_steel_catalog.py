"""Import only the pinned Flow dependencies needed by the steel demo."""
from __future__ import annotations

import json
import sys

from ..adapters.nebula_lca import NebulaLCAClient
from ..config import Settings
from ..errors import DomainError
from .standard_seed_bundle import SeedBuild, resolve_seed_directory
from .prepare_open_supply_flow import ensure_open_supply_flow
from .steel_catalog_prerequisite import load_steel_catalog_prerequisite


def _reference_flow_missing(error: DomainError) -> bool:
    return error.details.get("upstream_status") == 404


def main() -> int:
    steel_dir = resolve_seed_directory("iron-steel-bf-bof-crude-steel", None)
    steel = SeedBuild(steel_dir)
    steel.validate()
    prerequisites = {
        (item["seed_directory"], item["seed_id"], item["seed_version"], item["bundle_content_sha256"])
        for row in steel.flow_dependencies["dependencies"]
        if row["disposition"] == "verify_present"
        for item in [row.get("provided_by")]
        if item is not None
    }
    if len(prerequisites) != 1:
        raise ValueError("steel must name exactly one pinned catalog prerequisite")
    directory, seed_id, version, expected_hash = prerequisites.pop()

    expected_flows = [
        row for row in steel.flow_dependencies["dependencies"]
        if row.get("provided_by", {}).get("seed_directory") == directory
    ]
    descriptor, payload, source_rows = load_steel_catalog_prerequisite()
    if ((descriptor["source_seed_id"], descriptor["source_seed_version"],
         descriptor["source_bundle_content_sha256"]) != (seed_id, version, expected_hash)):
        raise ValueError("catalog resource differs from the steel source pin")
    if {row["flow_uuid"] for row in expected_flows} != {row["flow_uuid"] for row in source_rows}:
        raise ValueError("catalog resource has a different Flow selection")
    for dependency in expected_flows:
        source = next(row for row in source_rows if row["flow_uuid"] == dependency["flow_uuid"])
        if any(source.get(key) != value for key, value in dependency["observed"].items()):
            raise ValueError("catalog resource Flow differs from the steel pin: " + dependency["role"])
    settings = Settings.from_env()
    client = NebulaLCAClient(settings.nebula_lca_base_url, settings.nebula_lca_timeout_seconds)
    try:
        def missing_or_drift() -> list[str]:
            problems = []
            for dependency in expected_flows:
                try:
                    observed = client.get_reference_flow(dependency["flow_uuid"])
                except DomainError as error:
                    if _reference_flow_missing(error):
                        problems.append(dependency["role"] + ": missing")
                        continue
                    raise
                differences = [
                    key for key, value in dependency["observed"].items()
                    if observed.get(key) != value
                ]
                if differences:
                    problems.append(dependency["role"] + ": " + ",".join(differences))
            return problems

        before = missing_or_drift()
        if before:
            receipt = client.restore_native_catalog_flows(
                filename=descriptor["asset"], payload=payload,
                flow_uuids=[row["flow_uuid"] for row in expected_flows],
            ).payload
            if receipt["source_project_id"] != descriptor["source_project_id"]:
                raise ValueError("engine imported a different prerequisite project")
        after = missing_or_drift()
        if after:
            raise ValueError("catalog prerequisite did not match the steel pin: " + "; ".join(after))
        supply_flow = ensure_open_supply_flow(client)
        print(json.dumps({"status": "ready", "seed": f"{seed_id}@{version}",
                          "bundle_content_sha256": expected_hash,
                          "verified_flow_uuids": sorted(row["flow_uuid"] for row in expected_flows),
                          "open_supply_flow": supply_flow}))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (DomainError, ValueError) as error:
        print(f"steel catalog preparation refused: {error}", file=sys.stderr)
        sys.exit(1)
