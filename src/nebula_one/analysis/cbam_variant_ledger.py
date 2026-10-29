"""Compile a user-declared counted ledger from a frozen, reviewed base universe.

The base package remains immutable. This artifact cites both its exact hash and the
immutable user method; it describes a user variant and makes no regulatory review claim.
"""
from __future__ import annotations

from copy import deepcopy

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def compile_variant_ledger(*, rules, ledger, selection, user_method, base_ref, base_hash):
    def refuse(message):
        raise DomainError(code="CBAM_USER_LEDGER_MISMATCH", message=message, status_code=409)

    source = {key: user_method.get(key) for key in ("method_id", "version", "content_sha256")}
    if not all(source.values()):
        refuse("The user-declared counted ledger requires an exact frozen method identity.")
    base = {str(rule["exchange_id"]): rule for rule in rules}
    if len(base) != len(rules) or {k for k, v in ledger.items() if v.get("disposition") == "counted"} != set(base):
        refuse("The original boundary must agree with the reviewed base counted universe.")
    decisions = {str(item["exchange_id"]): item for item in selection["decisions"]}
    if len(decisions) != len(selection["decisions"]):
        refuse("The frozen emission selection decides an exchange more than once.")
    included = set(selection["included_exchange_ids"])
    excluded = set(selection["excluded_exchange_ids"])
    if not included <= set(base) or not set(base) <= set(decisions):
        refuse("A user variant may only narrow the exact reviewed counted universe.")
    clause = f"user-variant-exclusion@{source['method_id']}@{source['version']}#{source['content_sha256']}"
    compiled = deepcopy(ledger)
    rows = []
    for exchange_id, rule in sorted(base.items()):
        decision = decisions[exchange_id]
        if exchange_id in included:
            if decision.get("state") != "included":
                refuse("Included identities disagree with the frozen decisions.")
            state = "counted"
        elif exchange_id in excluded and decision.get("state") == "excluded" and decision.get("clause") == clause:
            state = "excluded_with_basis"
            compiled[exchange_id] = {**compiled[exchange_id], "disposition": state,
                                     "clause": clause, "basis": "user_declared_method_variant"}
            compiled[exchange_id].pop("source_group", None)
            compiled[exchange_id].pop("counted_instead", None)
        else:
            refuse("An exclusion lacks the exact user method declaration frozen by the solve.")
        rows.append({"exchange_id": exchange_id, "identity": deepcopy(rule),
                     "disposition": state, "clause": decision["clause"]})
    linked_exclusions = []
    for exchange_id, entry in compiled.items():
        chosen = entry.get("counted_instead")
        if chosen in set(base) - included:
            # Its alternate source is now explicitly outside this USER boundary too.
            # Retain the reviewed relationship in the artifact; do not promote the input
            # into a new counted emission or leave a false counted-source backlink.
            linked_exclusions.append({"exchange_id": exchange_id, "base_disposition": deepcopy(entry),
                                      "excluded_source_exchange_id": chosen})
            entry.pop("source_group", None)
            entry.pop("counted_instead", None)
            entry.update(clause=clause, basis="user_declared_method_variant_source_excluded")
    artifact = {"schema_version": "nebula_one.cbam.user-declared-counted-ledger.v1",
                "compiler_version": "1.0.0", "base_method_package_ref": base_ref,
                "base_method_package_sha256": base_hash, "user_method": source,
                "selection_sha256": canonical_json_sha256(selection), "entries": rows,
                "linked_source_exclusions": linked_exclusions,
                "claim": "user_declared_variant_not_regulatory_baseline"}
    artifact["content_sha256"] = canonical_json_sha256(artifact)
    return [rule for rule in rules if rule["exchange_id"] in included], compiled, artifact
