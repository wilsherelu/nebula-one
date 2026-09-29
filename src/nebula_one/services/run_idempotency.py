from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from ..hashing import canonical_json_sha256


RUN_ID_NAMESPACE = UUID("b05e5363-d7c4-4c9c-8f36-8507812ebf49")


def build_run_identity(
    *,
    run_kind: str,
    scope_id: str,
    explicit_idempotency_key: str | None,
    request_basis: dict[str, Any],
) -> tuple[str, str, str]:
    request_sha256 = canonical_json_sha256(request_basis)
    idempotency_key = explicit_idempotency_key or f"auto:{request_sha256}"
    run_id = str(
        uuid5(
            RUN_ID_NAMESPACE,
            f"nebula-one.run.v1\n{run_kind}\n{scope_id}\n{idempotency_key}",
        )
    )
    return run_id, idempotency_key, request_sha256
