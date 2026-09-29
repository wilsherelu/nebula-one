from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def read_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise RuntimeError(f"invalid compatibility pin: {raw_line}")
        pins[key.strip()] = value.strip()
    return pins


def git(engine_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=engine_dir,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engine-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "nebula-lca",
    )
    parser.add_argument(
        "--pin-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "deploy" / "engine.env",
    )
    parser.add_argument("--require-clean-app", action="store_true")
    args = parser.parse_args()
    engine_dir = args.engine_dir.resolve()
    pins = read_pins(args.pin_file.resolve())
    expected_commit = pins.get("NEBULA_LCA_ENGINE_COMMIT", "")
    expected_version = pins.get("NEBULA_LCA_ENGINE_VERSION", "")
    actual_commit = git(engine_dir, "rev-parse", "HEAD")
    if expected_commit != actual_commit:
        raise RuntimeError(
            f"Nebula LCA commit mismatch: expected {expected_commit}, got {actual_commit}"
        )
    if git(engine_dir, "status", "--short"):
        raise RuntimeError("Nebula LCA worktree is not clean")
    if args.require_clean_app and git(Path(__file__).resolve().parents[1], "status", "--short"):
        raise RuntimeError("Nebula One worktree is not clean")
    print(
        json.dumps(
            {
                "status": "passed",
                "engine_dir": str(engine_dir),
                "engine_version": expected_version,
                "engine_commit": actual_commit,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
