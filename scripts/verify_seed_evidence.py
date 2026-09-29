"""Verify a seed evidence directory from a checkout: its manifest pins, and the identities it claims.

This is the durable, path-free version of what `tmp/segment9h_54_steel_identity_and_manifest.py`
writes. tmp/ is not recoverable from a clone, so a reviewer who wants to re-check an evidence
directory - after the ammonia slice shipped a manifest that only verified against a CRLF worktree -
needs this.

Two checks, kept apart:

`manifest`  every line of `manifest.sha256` against the bytes a checkout actually yields. The
            default is the staged blob (`git cat-file blob :<path>`); `--ref <commit>` reads that
            commit instead. A line that matches only the working copy is a failure, not a pass:
            `.gitattributes` (`*.json text eol=lf`) can make the two differ.
`identity`  the values `identity.json` attributes to the **authored content in this repository** -
            each seed's version, its bundle pin recomputed through the build gate, and each method
            package's canonical hash - are recomputed from `cases/standard-lca-seeds/`. Anything
            that depends on a run (snapshot ids, solve hashes, engine receipts, database columns) is
            reported as `not_checked_here`, because a checkout has no `runtime/` to read it from.

Nothing here writes to a database, contacts a service, or resolves a path outside the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nebula_one.hashing import canonical_json_sha256  # noqa: E402
from nebula_one.runtime_schemas import MethodPackageCreate  # noqa: E402
from nebula_one.seeds import standard_seed_bundle  # noqa: E402

MANIFEST_NAME = "manifest.sha256"
# identity.json keys that describe a particular boot rather than the authored content
RUNTIME_SCOPED = (
    "databases",
    "solved_system_snapshots",
    "results_by_application",
    "cbam_trial_boundaries",
    "periods",
    "applications_stored",
    "derived_versus_answer_across_two_boots",
    "autoload_manifests",
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, cwd=ROOT)


def check_manifest(evidence: Path, ref: str) -> dict:
    path = evidence / MANIFEST_NAME
    if not path.is_file():
        return {"present": False}
    text = path.read_text(encoding="utf-8")
    listed = [line.split("  ", 1) for line in text.splitlines() if line.strip()]
    worktree_mismatches, blob_mismatches, missing_from_index = [], [], []
    for digest, rel in listed:
        target = evidence / rel
        if not target.is_file():
            worktree_mismatches.append(rel)
            continue
        if sha256_bytes(target.read_bytes()) != digest:
            worktree_mismatches.append(rel)
        repo_path = (evidence.relative_to(ROOT) / rel).as_posix()
        tracked = git("ls-files", "--stage", "--", repo_path).stdout.decode().strip()
        if not tracked:
            missing_from_index.append(repo_path)
            continue
        blob = git("cat-file", "blob", f"{ref}:{repo_path}" if ref != ":" else f":{repo_path}")
        if blob.returncode != 0 or sha256_bytes(blob.stdout) != digest:
            blob_mismatches.append(repo_path)
    # The CR rule guards line-ending normalisation, so it applies to the files git may rewrite on
    # checkout; a declared-binary file (PNG image data) legitimately contains 0x0D bytes, and asking
    # git is what decides rather than a hardcoded extension list that would drift from .gitattributes.
    carriage_returns, cr_bytes_in_binary = [], 0
    for item in sorted(p for p in evidence.rglob("*") if p.is_file() and p.name != MANIFEST_NAME):
        rel = item.relative_to(evidence).as_posix()
        if b"\r" not in item.read_bytes():
            continue
        check_path = (evidence.relative_to(ROOT) / rel).as_posix()
        if git("check-attr", "binary", "--", check_path).stdout.decode().rsplit(":", 1)[-1].strip() \
                in ("set", "true"):
            cr_bytes_in_binary += 1
            continue
        carriage_returns.append(rel)
    return {
        "present": True,
        "verified_against": ref or "staged index",
        "lines": len(listed),
        "manifest_excludes_itself": not any(rel == MANIFEST_NAME for _, rel in listed),
        "manifest_is_lf": "\r" not in text,
        "every_line_matches_the_worktree": not worktree_mismatches,
        "worktree_mismatches": worktree_mismatches,
        "every_line_matches_a_git_blob": not blob_mismatches and not missing_from_index,
        "blob_mismatches": blob_mismatches,
        "not_in_git_at_all": missing_from_index,
        "files_containing_carriage_returns": carriage_returns,
        "cr_bytes_in_git_declared_binary_files": cr_bytes_in_binary,
    }


def authored_seed_identity(seed_dir: Path) -> dict:
    """Re-derive from tracked files what identity.json attributes to the authored seed."""
    build = standard_seed_bundle.SeedBuild(seed_dir)
    packages = {}
    for entry in build.manifest["method_package_refs"]:
        payload_path = seed_dir / entry["path"]
        payload = MethodPackageCreate.model_validate(json.loads(payload_path.read_text(encoding="utf-8")))
        key = f"{payload.package_id}@{payload.version}"
        packages[key] = {
            "path": payload_path.relative_to(ROOT).as_posix(),
            "canonical_sha256": canonical_json_sha256(payload.model_dump(mode="json")),
            "declared_in_seed_manifest": entry.get("content_sha256"),
        }
        packages[key]["declaration_matches_file"] = (
            packages[key]["canonical_sha256"] == entry.get("content_sha256")
        )
    return {
        "seed_id": build.manifest["seed_id"],
        "version": build.manifest["version"],
        "bundle_content_sha256": build.manifest["content_pins"]["bundle_content_sha256"],
        "packages": packages,
    }


def find_seed_directory(seed_id: str) -> Path | None:
    """identity.json records a seed by its id, not by path, so match the manifest's own seed_id."""
    for candidate in sorted((ROOT / "cases/standard-lca-seeds").iterdir()):
        manifest_path = candidate / "seed.json"
        if not manifest_path.is_file():
            continue
        if json.loads(manifest_path.read_text(encoding="utf-8")).get("seed_id") == seed_id:
            return candidate
    return None


def check_identity(evidence: Path) -> dict:
    path = evidence / "identity.json"
    if not path.is_file():
        return {"present": False}
    recorded = json.loads(path.read_text(encoding="utf-8"))
    recomputed = {}
    disagreements = []
    for seed_id, entry in (recorded.get("seeds") or {}).items():
        seed_dir = find_seed_directory(seed_id)
        theirs = entry.get("authored") or {}
        if seed_dir is None:
            disagreements.append(f"{seed_id}: no seed.json in cases/standard-lca-seeds claims this id")
            continue
        mine = authored_seed_identity(seed_dir)
        recomputed[seed_id] = {"seed_directory": seed_dir.relative_to(ROOT).as_posix(), **mine}
        for field, value in (
            ("version", mine["version"]),
            ("bundle_content_sha256_recomputed_through_the_build_gate", mine["bundle_content_sha256"]),
        ):
            if field in theirs and str(theirs[field]) != str(value):
                disagreements.append(f"{seed_id}.{field}: recorded {theirs[field]} != recomputed {value}")
        for key, package in mine["packages"].items():
            stated = (entry.get("packages_declared_by_this_seed") or {}).get(key) or {}
            file_hash = stated.get("file_content_sha256")
            if file_hash and file_hash != package["canonical_sha256"]:
                disagreements.append(
                    f"{seed_id}.{key}: recorded file hash {file_hash} != recomputed "
                    f"{package['canonical_sha256']}"
                )
    return {
        "present": True,
        "generated_at_utc_the_directory_was_written": recorded.get("generated_at_utc"),
        "seeds_recomputed": sorted(recomputed),
        "recomputed_values": recomputed,
        "disagreements_between_recorded_and_recomputed": disagreements,
        "not_checked_here": list(RUNTIME_SCOPED),
        "why_those_are_left_out": "they describe one boot's answers and are read out of SQLite files "
        "under runtime/, which is gitignored; a checkout cannot tell a wrong value from a "
        "different run, so this script does not pretend to",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--evidence",
        required=True,
        help="evidence directory, relative to the repository root",
    )
    parser.add_argument(
        "--ref",
        default=":",
        help="commit to read blobs from; the default reads the staged index",
    )
    parser.add_argument("--only", choices=("manifest", "identity"), help="run one check")
    arguments = parser.parse_args()

    evidence = (ROOT / arguments.evidence).resolve()
    if ROOT not in evidence.parents:
        raise SystemExit(f"{evidence} is not inside {ROOT}")
    report = {"evidence_directory": evidence.relative_to(ROOT).as_posix()}
    if arguments.only in (None, "manifest"):
        report["manifest"] = check_manifest(evidence, arguments.ref)
    if arguments.only in (None, "identity"):
        report["identity"] = check_identity(evidence)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    checks = []
    if "manifest" in report and arguments.only != "identity":
        manifest = report["manifest"]
        checks.append(bool(manifest.get("present")))
        checks.extend(
            [manifest["manifest_excludes_itself"], manifest["manifest_is_lf"],
             manifest["every_line_matches_the_worktree"], manifest["every_line_matches_a_git_blob"],
             not manifest["files_containing_carriage_returns"]]
        )
    if "identity" in report:
        identity = report["identity"]
        checks.append(bool(identity.get("present")))
        checks.append(not identity["disagreements_between_recorded_and_recomputed"])
    passed = bool(checks) and all(checks)
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
