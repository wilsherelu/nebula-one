# Nebula One backend architecture

## Boundary

```text
Nebula One application backend
  entity/boundary/inventory, Flow/Process/System revisions, scenarios and evidence
                         |
                         | versioned HTTP contract
                         v
Nebula LCA modelling engine
  TIDAS graph contracts, model versions, validation, LCI/LCIA solver orchestration
```

Nebula One requires a reachable Nebula LCA API for model onboarding and calculation. It never imports `nebula-lca-api/app`, embeds a solver, or reads the engine database. Three model sources converge on one exact `SystemModel`: an existing project version, a TIDAS bundle imported by the engine, or a lossless `.nebula.zip` restored by the engine. Nebula One stores only source hashes and receipts, the exact engine project/version identity, the graph snapshot, and application revisions. Flow, Process, and System operations are applied locally to an explicitly selected parent revision. LCIA runs call the existing `POST /api/model/run` contract with the selected revision graph. Publishing is a separate, explicit-confirmation action that calls `POST /api/projects/{project_id}/versions`; Nebula One does not publish TIDAS records or copy solver/data packages.

## Core mechanism

```text
exact engine pin
      |
      v
base System revision ---- operation ----> child revision ---- analysis
      |                         |
      +---- another operation --+----> alternative branch ---- analysis
                                      |
                                      +---- confirmed publish --> new engine version
```

The three object levels have stable roles:

- **Flow** is represented by typed input/output/emission ports plus directed exchanges. Flow operations edit ports, connect or disconnect exchanges, and preserve explicit endpoint evidence.
- **Process** is a transformation or activity node containing Flow ports. Process operations add, update, or remove a node; structural port edits must go through Flow operations.
- **System** is the bounded Process/Flow graph plus functional unit and application context. System operations change system-wide semantics or scale an explicitly selected physical-flow scope.

An operation never changes its parent. It produces a child with a graph hash, graph-plus-context content hash, parent ID, monotonic revision number, and operation receipt. Branching is therefore a normal scenario mechanism, not a mutable "current model" flag.

## Sustainability runtime

```text
TIDAS evidence and master-data references
                 |
Entity + BoundaryDefinition + Period
                 |
InventorySnapshot ---- ParameterSet
                 |             |
                 +-- Scenario -+-- SystemRevision
                           |
                     AnalysisPlan
                           |
              SolvedSystemSnapshot / AnalysisRun
                           |
                    ResultSet -> EvidencePack
```

SystemRevision represents model structure and process coefficients. InventorySnapshot represents observed activity data for a period. Scenario freezes the exact combination instead of turning monthly meter, invoice, production, transport, waste, or monitoring changes into graph revisions. ResultSet is the sparse result-cube contract; EvidencePack records the complete lineage back to evidence hashes, mapping targets, model and scenario hashes, solver receipts, method package versions, and source runs.

## Modules

- `adapters/nebula_lca.py`: the only Nebula LCA HTTP boundary; proxy inheritance is disabled and upstream errors are normalized without fake fallback results.
- `analysis/mfa.py`: deterministic post-model projection over declared graph amounts. It does not replace the matrix solver and does not claim solved-activity scaling.
- `casepacks/contracts.py`, `casepacks/loader.py`, `casepacks/licenses.py`, `casepacks/provider_candidates.py`, and `casepacks/bindings.py`: strict versioned case contracts, canonical hashes, root-confined loading, exact reference and license-evidence validation, fail-closed provider candidate gates, deterministic load receipts, and frozen parameter expansion into existing ModelOperation batches.
- `services/system_models.py`: exact upstream version resolution, graph hashing, and immutable local snapshot creation.
- `services/model_sources.py`: TIDAS dry-run/import and native bundle inspect/restore orchestration, exact version selection, source receipts, and dependency-based solve gates.
- `domain/operations.py`: pure Flow, Process, and System operation semantics plus post-operation structural validation.
- `services/system_revisions.py`: revision branching, operation receipts, and confirmed publication.
- `services/parameter_bindings.py`: verifies frozen ParameterSet ownership and parent revision hashes before resolving and idempotently applying a binding batch.
- `services/analysis_runs.py`: persisted run state transitions and calculation receipts.
- `services/registry.py`: Entity, Period, BoundaryDefinition, MethodPackage, and model bindings.
- `services/inventory.py`: evidence, period inventory data points, snapshot review/freeze, and parameter sets.
- `services/scenarios.py`: frozen scenarios, plans, and functional-unit/boundary/period/method comparability checks.
- `services/results.py`: solved-system receipt validation, result sets, and evidence lineage assembly.
- `resources/application_profiles.json`: application intent and extension requirements, separate from executable calculations.
- `resources/product_blueprint.json`: machine-readable composition from core objects to analysis layers and sustainability applications.
- `api.py`: HTTP parsing and response contracts only.

## Version 0.2 executable and contract capabilities

| Capability | Execution boundary | Evidence |
|---|---|---|
| `mfa.declared.v1` | local deterministic projection of the pinned public HybridGraph | graph SHA-256, unit-group series, boundary/internal totals and process balances |
| `lcia.nebula.v1` | existing Nebula LCA `/api/model/run` | upstream run ID/status and unmodified result snapshot |
| `solve.nebula.v1` | Nebula LCA provider v1 with structured demand | consumer/provider graph hashes, true activity vector, scaled exchanges, inventory totals and solve provenance |
| `mfa.solved.v1` | frozen `SolvedSystemSnapshot` plus selected system revision | unit-series aggregation, internal-transfer reconciliation, boundary-flow totals, process balance diagnostics and traceable Sankey SVG |
| `ModelOperation v1` | local atomic operation batch | idempotency key, expected parent hash, ordered receipts, one child revision |
| `ParameterBinding v1` | strict expansion of a frozen ParameterSet against one exact parent revision | binding/parameter/parent hashes, ordered operation set, unit checks and deterministic batch idempotency |
| sustainability runtime | local persisted domain lifecycle | frozen entity/boundary/period/inventory/parameter/scenario hashes |
| solved-system freezing | provider v1 execution plus provider-neutral immutable contract | exact frozen-input hashes, persisted AnalysisRun, succeeded provider receipt and frozen solved output |
| result/evidence | local deterministic projection | result hash and full evidence lineage |

Application profiles such as CBAM, zero-carbon park, enterprise ESG, and project carbon evaluation are not aliases for fabricated calculations. They describe the method packages and executable capabilities required for later releases. A profile may be created now, but only registered executable capabilities can be run.

## Reproducibility contract

Every system model requires a concrete upstream project ID and positive integer version. `latest` is prohibited. Nebula One calculates SHA-256 over canonical UTF-8 JSON for the returned graph and stores the graph, version, upstream creation time, source policy, and LCIA scope. Every child revision records its parent and canonical graph/content hashes. Every run records the selected revision, capability key, parameters, model hash, provider endpoint, provider receipt, result or structured error, and timestamps.

Nebula One and Nebula LCA are released independently but evolve against a capability contract. A Nebula One release records the tested Nebula LCA commit and required OpenAPI paths; deployment images and desktop sidecars use fixed versions rather than a floating `latest` tag. A newer engine is accepted only after capability probing and the cross-repository regression case has passed.

## Known first-version limits

- Declared MFA uses declared port and edge amounts; solved MFA is a separate capability and only consumes provider-scaled exchanges frozen in a `SolvedSystemSnapshot`.
- Cross-unit conversions, dual-quantity conversions, temporal stock/cohort MFA, and geographic aggregation are not implemented.
- LCIA correctness remains owned by Nebula LCA and its selected data/method releases.
- CBAM, ESG, Scope 1/2/3, park accounting, and project baselines require versioned method packages and business/regulatory acceptance.
- The authoritative engine exposes provider v1 activity vectors and scaled exchanges, and Nebula One freezes them. The application layer now aggregates those frozen exchanges and renders Sankey output; its per-process balance is explicitly an application projection, not an engine matrix residual.
- PostgreSQL migrations, queued AnalysisRun, and provider-idempotent queued solve-and-freeze are implemented; scenario comparison parent/child recovery, authentication, tenant isolation, and full production recovery are not yet complete.
