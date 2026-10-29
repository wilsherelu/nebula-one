"""Prepare local, parentless source candidates without changing existing history or remotes."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
from build_payload import FORBIDDEN_CHARACTERIZATION_SHA256


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True, encoding="utf-8").strip()


def audit(data: bytes, label: str, problems: list[str], depth: int = 0) -> int:
    """Also inspect tracked nested ZIPs, rather than trusting their outer names."""
    digest = hashlib.sha256(data).hexdigest()
    if digest in FORBIDDEN_CHARACTERIZATION_SHA256:
        problems.append(f"{label}: {FORBIDDEN_CHARACTERIZATION_SHA256[digest]}")
    name = label.replace("\\", "/").split("!/")[-1]
    if name.endswith((".db", ".sqlite", ".sqlite3", ".pem", ".key")):
        problems.append(f"{label}: database or key file")
    if name.split("/")[-1] == ".env":
        problems.append(f"{label}: private environment file")
    if name.endswith("ecoinvent_ef31_climate_total_311.v1.json"):
        problems.append(f"{label}: commercial method asset")
    if "/.git/" in f"/{name}":
        problems.append(f"{label}: Git object or metadata")
    count = 1
    if zipfile.is_zipfile(io.BytesIO(data)):
        if depth >= 4:
            problems.append(f"{label}: nested archive depth exceeds audit limit")
            return count
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for entry in archive.infolist():
                if not entry.is_dir():
                    count += audit(archive.read(entry), f"{label}!/{entry.filename}", problems, depth + 1)
    return count


def prepare(repo: Path, output: Path, ref: str) -> dict:
    if git(repo, "status", "--porcelain"):
        raise RuntimeError(f"Commit scoped work before preparing {repo}")
    head = git(repo, "rev-parse", "HEAD")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    archive = output / f"{repo.name}-0.1.1-source.zip"
    if archive.exists():
        raise FileExistsError(archive)
    subprocess.run(["git", "archive", "--format=zip", f"--output={archive}", head], cwd=repo, check=True)
    problems: list[str] = []
    count = audit(archive.read_bytes(), archive.name, problems)
    if problems:
        raise RuntimeError(json.dumps(problems, ensure_ascii=False))
    # A new root is independent of historical commercial blobs; main and its ancestors stay intact.
    candidate = git(repo, "commit-tree", tree, "-m", "Local public 0.1.1 source candidate; existing history preserved")
    subprocess.run(["git", "update-ref", ref, candidate, "0" * 40], cwd=repo, check=True)
    assert git(repo, "rev-list", "--count", ref) == "1"
    assert git(repo, "rev-parse", f"{ref}^{{tree}}") == tree
    assert git(repo, "rev-parse", "HEAD") == head
    return {"repo": str(repo), "main_head": head, "candidate_ref": ref, "candidate_commit": candidate,
            "tree": tree, "reachable_commits": 1, "archive": str(archive),
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "audited_entries_including_nested": count, "known_forbidden_assets": [],
            "scope": "Known asset hashes and database/key/env paths; not a complete legal or secret audit"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lca-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ref", default="refs/heads/public-candidate/0.1.1-20261018")
    args = parser.parse_args()
    if not args.ref.startswith("refs/heads/public-candidate/"):
        raise ValueError("Only a new public-candidate branch may be created")
    args.output.mkdir(parents=True, exist_ok=True)
    reports = [prepare(repo, args.output, args.ref) for repo in (ROOT, args.lca_root.resolve())]
    (args.output / "source-candidates.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
